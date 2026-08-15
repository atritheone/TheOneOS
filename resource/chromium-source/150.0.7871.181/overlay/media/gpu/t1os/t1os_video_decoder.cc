// Copyright 2026 The One OS Authors
// Use of this source code is governed by a BSD-style license.

#include "media/gpu/t1os/t1os_video_decoder.h"

#include <fcntl.h>
#include <linux/dma-buf.h>
#include <linux/memfd.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>

#include <algorithm>
#include <array>
#include <cstring>
#include <limits>
#include <optional>
#include <utility>
#include <vector>

#include "base/containers/span.h"
#include "base/functional/bind.h"
#include "base/functional/callback_helpers.h"
#include "base/logging.h"
#include "base/notreached.h"
#include "base/numerics/checked_math.h"
#include "base/numerics/safe_conversions.h"
#include "base/posix/eintr_wrapper.h"
#include "base/task/sequenced_task_runner.h"
#include "base/time/time.h"
#include "media/base/color_plane_layout.h"
#include "media/base/decoder_buffer.h"
#include "media/base/media_log.h"
#include "media/base/video_color_space.h"
#include "media/base/video_frame.h"
#include "media/base/video_frame_layout.h"
#include "media/base/video_types.h"
#include "media/gpu/chromeos/frame_resource_converter.h"
#include "media/gpu/chromeos/native_pixmap_frame_resource.h"
#include "ui/gfx/native_pixmap_handle.h"
#include "media/gpu/t1os/t1os_decoder_connection.h"
#include "ui/gfx/geometry/rect.h"
#include "ui/gfx/geometry/size.h"

namespace media {
namespace {

// The native supervisor is authoritative: CREATE/DECODE/FLUSH are bounded by
// 15 seconds and RESET by 10 seconds while actively running. Chromium's
// watchdogs are deliberately longer fallbacks. RESET can sit behind the
// serialized 15-second operation, so its fallback covers both native windows.
// Explicit BACKPRESSURE pauses a DECODE/FLUSH watchdog until matching EXIT.
constexpr base::TimeDelta kCreateOperationTimeout = base::Seconds(20);
constexpr base::TimeDelta kDecodeOperationTimeout = base::Seconds(30);
constexpr base::TimeDelta kFlushOperationTimeout = base::Seconds(30);
constexpr base::TimeDelta kResetOperationTimeout = base::Seconds(35);

DecoderStatus StatusFromT1(uint32_t status, bool initializing = false) {
  switch (status) {
    case T1_MEDIA_STATUS_OK:
      return DecoderStatus(DecoderStatus::Codes::kOk);
    case T1_MEDIA_STATUS_BUSY:
    case T1_MEDIA_STATUS_RESOURCE_EXHAUSTED:
      return DecoderStatus(DecoderStatus::Codes::kTooManyDecoders);
    case T1_MEDIA_STATUS_UNSUPPORTED_CODEC:
      return DecoderStatus(DecoderStatus::Codes::kUnsupportedCodec);
    case T1_MEDIA_STATUS_UNSUPPORTED_PROFILE:
      return DecoderStatus(DecoderStatus::Codes::kUnsupportedProfile);
    case T1_MEDIA_STATUS_UNSUPPORTED_CONFIGURATION:
      return DecoderStatus(DecoderStatus::Codes::kUnsupportedConfig);
    case T1_MEDIA_STATUS_DECODE_ERROR:
      return DecoderStatus(DecoderStatus::Codes::kPlatformDecodeFailure);
    case T1_MEDIA_STATUS_HARDWARE_UNAVAILABLE:
      return DecoderStatus(initializing
                               ? DecoderStatus::Codes::kFailedToCreateDecoder
                               : DecoderStatus::Codes::kPlatformDecodeFailure);
    case T1_MEDIA_STATUS_SERVICE_STOPPING:
      return DecoderStatus(DecoderStatus::Codes::kDisconnected);
    default:
      return DecoderStatus(DecoderStatus::Codes::kFailed);
  }
}

uint32_t CodecToT1(VideoCodec codec) {
  switch (codec) {
    case VideoCodec::kH264:
      return T1_MEDIA_CODEC_H264;
    case VideoCodec::kVP8:
      return T1_MEDIA_CODEC_VP8;
    case VideoCodec::kVP9:
      return T1_MEDIA_CODEC_VP9;
    case VideoCodec::kHEVC:
      return T1_MEDIA_CODEC_HEVC;
    case VideoCodec::kAV1:
      return T1_MEDIA_CODEC_AV1;
    default:
      return T1_MEDIA_CODEC_UNKNOWN;
  }
}

uint32_t BitDepthForProfile(VideoCodecProfile profile) {
  switch (profile) {
    case VP9PROFILE_PROFILE2:
    case VP9PROFILE_PROFILE3:
    case HEVCPROFILE_MAIN10:
      return 10;
    case AV1PROFILE_PROFILE_MAIN:
      // Chromium's AV1 Main profile represents both 8- and 10-bit streams and
      // VideoDecoderConfig does not carry a bit-depth field.  Zero asks T1MD to
      // derive the depth from the decoded AVFrame and is legal only for AV1
      // Main; the worker then validates it against its advertised mask.
      return 0;
    default:
      return 8;
  }
}

uint32_t BitDepthFlag(uint32_t bit_depth) {
  switch (bit_depth) {
    case 8:
      return T1_MEDIA_BIT_DEPTH_8;
    case 10:
      return T1_MEDIA_BIT_DEPTH_10;
    default:
      return 0;
  }
}

bool CapabilitiesSupportCreate(const t1_media_capabilities& capabilities,
                               uint32_t codec,
                               uint32_t profile,
                               uint32_t bit_depth) {
  for (const auto& capability :
       base::span(capabilities.profiles).first(capabilities.profile_count)) {
    if (capability.codec != codec || capability.profile != profile) {
      continue;
    }
    if (bit_depth == 0) {
      if (codec != T1_MEDIA_CODEC_AV1 ||
          profile != T1_MEDIA_PROFILE_AV1_MAIN ||
          (capability.bit_depths &
           (T1_MEDIA_BIT_DEPTH_8 | T1_MEDIA_BIT_DEPTH_10)) == 0) {
        return false;
      }
      const bool usable_8 =
          (capability.bit_depths & T1_MEDIA_BIT_DEPTH_8) != 0 &&
          (capability.output_formats & T1_MEDIA_OUTPUT_NV12) != 0;
      const bool usable_10 =
          (capability.bit_depths & T1_MEDIA_BIT_DEPTH_10) != 0 &&
          (capability.output_formats & T1_MEDIA_OUTPUT_P010) != 0;
      return usable_8 || usable_10;
    }
    const uint32_t depth_flag = BitDepthFlag(bit_depth);
    const uint32_t output_flag = bit_depth == 8 ? T1_MEDIA_OUTPUT_NV12
                                                : T1_MEDIA_OUTPUT_P010;
    return depth_flag != 0 &&
           (capability.bit_depths & depth_flag) != 0 &&
           (capability.output_formats & output_flag) != 0;
  }
  return false;
}

uint32_t PrimaryToT1(VideoColorSpace::PrimaryID primary) {
  switch (primary) {
    case VideoColorSpace::PrimaryID::BT709:
      return 1;
    case VideoColorSpace::PrimaryID::UNSPECIFIED:
      return 2;
    case VideoColorSpace::PrimaryID::BT470M:
      return 4;
    case VideoColorSpace::PrimaryID::BT470BG:
      return 5;
    case VideoColorSpace::PrimaryID::SMPTE170M:
      return 6;
    case VideoColorSpace::PrimaryID::SMPTE240M:
      return 7;
    case VideoColorSpace::PrimaryID::FILM:
      return 8;
    case VideoColorSpace::PrimaryID::BT2020:
      return 9;
    case VideoColorSpace::PrimaryID::SMPTEST428_1:
      return 10;
    case VideoColorSpace::PrimaryID::SMPTEST431_2:
      return 11;
    case VideoColorSpace::PrimaryID::SMPTEST432_1:
      return 12;
    case VideoColorSpace::PrimaryID::EBU_3213_E:
      return 22;
    case VideoColorSpace::PrimaryID::INVALID:
      return 0;
  }
  NOTREACHED();
}

uint32_t TransferToT1(VideoColorSpace::TransferID transfer) {
  switch (transfer) {
    case VideoColorSpace::TransferID::BT709:
      return 1;
    case VideoColorSpace::TransferID::UNSPECIFIED:
      return 2;
    case VideoColorSpace::TransferID::GAMMA22:
      return 4;
    case VideoColorSpace::TransferID::GAMMA28:
      return 5;
    case VideoColorSpace::TransferID::SMPTE170M:
      return 6;
    case VideoColorSpace::TransferID::SMPTE240M:
      return 7;
    case VideoColorSpace::TransferID::LINEAR:
      return 8;
    case VideoColorSpace::TransferID::LOG:
      return 9;
    case VideoColorSpace::TransferID::LOG_SQRT:
      return 10;
    case VideoColorSpace::TransferID::IEC61966_2_4:
      return 11;
    case VideoColorSpace::TransferID::BT1361_ECG:
      return 12;
    case VideoColorSpace::TransferID::IEC61966_2_1:
      return 13;
    case VideoColorSpace::TransferID::BT2020_10:
      return 14;
    case VideoColorSpace::TransferID::BT2020_12:
      return 15;
    case VideoColorSpace::TransferID::SMPTEST2084:
      return 16;
    case VideoColorSpace::TransferID::SMPTEST428_1:
      return 17;
    case VideoColorSpace::TransferID::ARIB_STD_B67:
      return 18;
    case VideoColorSpace::TransferID::INVALID:
      return 0;
  }
  NOTREACHED();
}

uint32_t MatrixToT1(VideoColorSpace::MatrixID matrix) {
  switch (matrix) {
    case VideoColorSpace::MatrixID::RGB:
      return 0;
    case VideoColorSpace::MatrixID::BT709:
      return 1;
    case VideoColorSpace::MatrixID::UNSPECIFIED:
      return 2;
    case VideoColorSpace::MatrixID::FCC:
      return 4;
    case VideoColorSpace::MatrixID::BT470BG:
      return 5;
    case VideoColorSpace::MatrixID::SMPTE170M:
      return 6;
    case VideoColorSpace::MatrixID::SMPTE240M:
      return 7;
    case VideoColorSpace::MatrixID::YCOCG:
      return 8;
    case VideoColorSpace::MatrixID::BT2020_NCL:
      return 9;
    case VideoColorSpace::MatrixID::BT2020_CL:
      return 10;
    case VideoColorSpace::MatrixID::YDZDX:
      return 11;
    case VideoColorSpace::MatrixID::INVALID:
      return 2;
  }
  NOTREACHED();
}

uint32_t RangeToT1(gfx::ColorSpace::RangeID range) {
  switch (range) {
    case gfx::ColorSpace::RangeID::LIMITED:
      return T1_MEDIA_COLOR_RANGE_LIMITED;
    case gfx::ColorSpace::RangeID::FULL:
      return T1_MEDIA_COLOR_RANGE_FULL;
    case gfx::ColorSpace::RangeID::INVALID:
    case gfx::ColorSpace::RangeID::DERIVED:
      return T1_MEDIA_COLOR_RANGE_UNSPECIFIED;
  }
  NOTREACHED();
}

bool ColorSpaceFromT1(const t1_media_frame& frame,
                      const VideoColorSpace& fallback,
                      VideoColorSpace* color_space) {
  VideoColorSpace::PrimaryID primary = fallback.primaries();
  switch (frame.color_primaries) {
    case 0:
    case 2:
      break;
    case 1:
      primary = VideoColorSpace::PrimaryID::BT709;
      break;
    case 4:
      primary = VideoColorSpace::PrimaryID::BT470M;
      break;
    case 5:
      primary = VideoColorSpace::PrimaryID::BT470BG;
      break;
    case 6:
      primary = VideoColorSpace::PrimaryID::SMPTE170M;
      break;
    case 7:
      primary = VideoColorSpace::PrimaryID::SMPTE240M;
      break;
    case 8:
      primary = VideoColorSpace::PrimaryID::FILM;
      break;
    case 9:
      primary = VideoColorSpace::PrimaryID::BT2020;
      break;
    case 10:
      primary = VideoColorSpace::PrimaryID::SMPTEST428_1;
      break;
    case 11:
      primary = VideoColorSpace::PrimaryID::SMPTEST431_2;
      break;
    case 12:
      primary = VideoColorSpace::PrimaryID::SMPTEST432_1;
      break;
    case 22:
      primary = VideoColorSpace::PrimaryID::EBU_3213_E;
      break;
    default:
      return false;
  }

  VideoColorSpace::TransferID transfer = fallback.transfer();
  switch (frame.color_transfer) {
    case 0:
    case 2:
      break;
    case 1:
      transfer = VideoColorSpace::TransferID::BT709;
      break;
    case 4:
      transfer = VideoColorSpace::TransferID::GAMMA22;
      break;
    case 5:
      transfer = VideoColorSpace::TransferID::GAMMA28;
      break;
    case 6:
      transfer = VideoColorSpace::TransferID::SMPTE170M;
      break;
    case 7:
      transfer = VideoColorSpace::TransferID::SMPTE240M;
      break;
    case 8:
      transfer = VideoColorSpace::TransferID::LINEAR;
      break;
    case 9:
      transfer = VideoColorSpace::TransferID::LOG;
      break;
    case 10:
      transfer = VideoColorSpace::TransferID::LOG_SQRT;
      break;
    case 11:
      transfer = VideoColorSpace::TransferID::IEC61966_2_4;
      break;
    case 12:
      transfer = VideoColorSpace::TransferID::BT1361_ECG;
      break;
    case 13:
      transfer = VideoColorSpace::TransferID::IEC61966_2_1;
      break;
    case 14:
      transfer = VideoColorSpace::TransferID::BT2020_10;
      break;
    case 15:
      transfer = VideoColorSpace::TransferID::BT2020_12;
      break;
    case 16:
      transfer = VideoColorSpace::TransferID::SMPTEST2084;
      break;
    case 17:
      transfer = VideoColorSpace::TransferID::SMPTEST428_1;
      break;
    case 18:
      transfer = VideoColorSpace::TransferID::ARIB_STD_B67;
      break;
    default:
      return false;
  }

  VideoColorSpace::MatrixID matrix = fallback.matrix();
  switch (frame.color_matrix) {
    case 2:
      break;
    case 0:
      matrix = VideoColorSpace::MatrixID::RGB;
      break;
    case 1:
      matrix = VideoColorSpace::MatrixID::BT709;
      break;
    case 4:
      matrix = VideoColorSpace::MatrixID::FCC;
      break;
    case 5:
      matrix = VideoColorSpace::MatrixID::BT470BG;
      break;
    case 6:
      matrix = VideoColorSpace::MatrixID::SMPTE170M;
      break;
    case 7:
      matrix = VideoColorSpace::MatrixID::SMPTE240M;
      break;
    case 8:
      matrix = VideoColorSpace::MatrixID::YCOCG;
      break;
    case 9:
      matrix = VideoColorSpace::MatrixID::BT2020_NCL;
      break;
    case 10:
      matrix = VideoColorSpace::MatrixID::BT2020_CL;
      break;
    case 11:
      matrix = VideoColorSpace::MatrixID::YDZDX;
      break;
    default:
      return false;
  }

  gfx::ColorSpace::RangeID range = fallback.range();
  switch (frame.color_range) {
    case T1_MEDIA_COLOR_RANGE_UNSPECIFIED:
      break;
    case T1_MEDIA_COLOR_RANGE_LIMITED:
      range = gfx::ColorSpace::RangeID::LIMITED;
      break;
    case T1_MEDIA_COLOR_RANGE_FULL:
      range = gfx::ColorSpace::RangeID::FULL;
      break;
    default:
      return false;
  }
  *color_space = VideoColorSpace(primary, transfer, matrix, range);
  return true;
}

bool IsValidDmaBufObject(int descriptor, uint64_t advertised_size) {
  if (advertised_size == 0) {
    return false;
  }
  const off_t actual_size = HANDLE_EINTR(lseek(descriptor, 0, SEEK_END));
  if (actual_size < 0 || static_cast<uint64_t>(actual_size) < advertised_size) {
    return false;
  }
  dma_buf_sync sync = {
      .flags = DMA_BUF_SYNC_START | DMA_BUF_SYNC_READ,
  };
  if (HANDLE_EINTR(ioctl(descriptor, DMA_BUF_IOCTL_SYNC, &sync)) != 0) {
    return false;
  }
  sync.flags = DMA_BUF_SYNC_END | DMA_BUF_SYNC_READ;
  return HANDLE_EINTR(ioctl(descriptor, DMA_BUF_IOCTL_SYNC, &sync)) == 0;
}

base::ScopedFD CreateSealedAccessUnit(const DecoderBuffer& buffer) {
  if (buffer.size() == 0 || buffer.size() > T1_MEDIA_MAX_ENCODED_BYTES) {
    return {};
  }
  base::ScopedFD fd(
      static_cast<int>(syscall(SYS_memfd_create, "t1os-chromium-access-unit",
                               MFD_CLOEXEC | MFD_ALLOW_SEALING)));
  if (!fd.is_valid() ||
      HANDLE_EINTR(
          ftruncate(fd.get(), base::checked_cast<off_t>(buffer.size()))) < 0) {
    return {};
  }

  base::span<const uint8_t> bytes(buffer);
  size_t written = 0;
  while (written < bytes.size()) {
    const base::span<const uint8_t> remaining = bytes.subspan(written);
    const ssize_t result =
        HANDLE_EINTR(write(fd.get(), remaining.data(), remaining.size()));
    if (result <= 0) {
      return {};
    }
    written += static_cast<size_t>(result);
  }
  constexpr int kRequiredSeals =
      F_SEAL_SEAL | F_SEAL_SHRINK | F_SEAL_GROW | F_SEAL_WRITE;
  if (HANDLE_EINTR(fcntl(fd.get(), F_ADD_SEALS, kRequiredSeals)) < 0) {
    return {};
  }
  return fd;
}

bool ParseResult(const T1OSDecoderPacket& packet, uint32_t* status) {
  if (packet.payload.size() != sizeof(t1_media_result) ||
      !packet.descriptors.empty()) {
    return false;
  }
  t1_media_result result = {};
  std::copy(packet.payload.begin(), packet.payload.end(),
            base::byte_span_from_ref(result).begin());
  if (result.reserved != 0) {
    return false;
  }
  *status = result.status;
  return true;
}

}  // namespace

bool ValidateT1OSFrameLayout(const t1_media_frame& frame,
                             size_t descriptor_count) {
  if ((frame.flags & T1_MEDIA_FRAME_SYNCHRONIZED) == 0 ||
      (frame.flags & ~(T1_MEDIA_FRAME_SYNCHRONIZED | T1_MEDIA_FRAME_INTERLACED |
                       T1_MEDIA_FRAME_TOP_FIELD_FIRST |
                       T1_MEDIA_FRAME_SEPARATE_LAYERS |
                       T1_MEDIA_FRAME_LINEAR_MEMORY)) != 0 ||
      ((frame.flags & T1_MEDIA_FRAME_TOP_FIELD_FIRST) != 0 &&
       (frame.flags & T1_MEDIA_FRAME_INTERLACED) == 0) ||
      frame.object_count == 0 ||
      frame.object_count > T1_MEDIA_MAX_FRAME_OBJECTS ||
      frame.layer_count == 0 || frame.layer_count > T1_MEDIA_MAX_FRAME_LAYERS ||
      descriptor_count != frame.object_count || frame.coded_width == 0 ||
      frame.coded_height == 0 ||
      frame.coded_width >
          static_cast<uint32_t>(std::numeric_limits<int>::max()) ||
      frame.coded_height >
          static_cast<uint32_t>(std::numeric_limits<int>::max()) ||
      frame.visible_width == 0 || frame.visible_height == 0 ||
      frame.visible_x >
          static_cast<uint32_t>(std::numeric_limits<int>::max()) ||
      frame.visible_y >
          static_cast<uint32_t>(std::numeric_limits<int>::max()) ||
      frame.visible_width >
          static_cast<uint32_t>(std::numeric_limits<int>::max()) ||
      frame.visible_height >
          static_cast<uint32_t>(std::numeric_limits<int>::max()) ||
      static_cast<uint64_t>(frame.visible_x) + frame.visible_width >
          frame.coded_width ||
      static_cast<uint64_t>(frame.visible_y) + frame.visible_height >
          frame.coded_height ||
      frame.chroma_location > T1_MEDIA_CHROMA_LOCATION_BOTTOM) {
    return false;
  }
  const bool linear_memory =
      (frame.flags & T1_MEDIA_FRAME_LINEAR_MEMORY) != 0;
  if (linear_memory &&
      (frame.object_count != 1 || frame.layer_count != 1 ||
       (frame.flags & T1_MEDIA_FRAME_SEPARATE_LAYERS) != 0 ||
       frame.objects[0].modifier != 0)) {
    return false;
  }
  if (!linear_memory &&
      ((frame.flags & T1_MEDIA_FRAME_SEPARATE_LAYERS) == 0 ||
       frame.object_count != 2 || frame.layer_count != 2)) {
    // Native DMA-BUF output is separate-layer only. Accepting a composed
    // descriptor or two nominal layers backed by one synthetic object here
    // would revive the common-modifier topology which NVIDIA rejects or
    // samples with corrupt chroma.
    return false;
  }

  uint64_t bytes_per_component = 0;
  uint32_t composed_format = 0;
  uint32_t luma_format = 0;
  uint32_t chroma_format = 0;
  uint32_t alternate_chroma_format = 0;
  if (frame.pixel_format == T1_MEDIA_PIXEL_FORMAT_NV12 &&
      frame.bit_depth == 8) {
    bytes_per_component = 1;
    composed_format = T1_MEDIA_DRM_FORMAT_NV12;
    luma_format = T1_MEDIA_DRM_FORMAT_R8;
    chroma_format = T1_MEDIA_DRM_FORMAT_RG88;
    alternate_chroma_format = T1_MEDIA_DRM_FORMAT_GR88;
  } else if (frame.pixel_format == T1_MEDIA_PIXEL_FORMAT_P010 &&
             frame.bit_depth == 10) {
    bytes_per_component = 2;
    composed_format = T1_MEDIA_DRM_FORMAT_P010;
    luma_format = T1_MEDIA_DRM_FORMAT_R16;
    chroma_format = T1_MEDIA_DRM_FORMAT_RG1616;
    alternate_chroma_format = T1_MEDIA_DRM_FORMAT_GR1616;
  } else {
    return false;
  }

  struct ExpectedPlane {
    t1_media_frame_plane plane = {};
    uint32_t height = 0;
    uint64_t minimum_row_bytes = 0;
    uint64_t required_end = 0;
  };
  std::array<ExpectedPlane, 2> expected = {};
  const uint32_t chroma_width = frame.coded_width / 2 + frame.coded_width % 2;
  const uint32_t chroma_height =
      frame.coded_height / 2 + frame.coded_height % 2;
  if ((frame.flags & T1_MEDIA_FRAME_SEPARATE_LAYERS) == 0) {
    const t1_media_frame_layer& layer = frame.layers[0];
    if (frame.layer_count != 1 || layer.drm_fourcc != composed_format ||
        layer.width != frame.coded_width ||
        layer.height != frame.coded_height || layer.plane_count != 2) {
      return false;
    }
    expected[0] = {
        .plane = layer.planes[0],
        .height = frame.coded_height,
        .minimum_row_bytes =
            static_cast<uint64_t>(frame.coded_width) * bytes_per_component,
    };
    expected[1] = {
        .plane = layer.planes[1],
        .height = chroma_height,
        .minimum_row_bytes =
            static_cast<uint64_t>(chroma_width) * 2u * bytes_per_component,
    };
  } else {
    const t1_media_frame_layer& luma = frame.layers[0];
    const t1_media_frame_layer& chroma = frame.layers[1];
    if (frame.layer_count != 2 || luma.drm_fourcc != luma_format ||
        (chroma.drm_fourcc != chroma_format &&
         chroma.drm_fourcc != alternate_chroma_format) ||
        luma.width != frame.coded_width ||
        luma.height != frame.coded_height || luma.plane_count != 1 ||
        chroma.width != chroma_width || chroma.height != chroma_height ||
        chroma.plane_count != 1) {
      return false;
    }
    expected[0] = {
        .plane = luma.planes[0],
        .height = frame.coded_height,
        .minimum_row_bytes =
            static_cast<uint64_t>(frame.coded_width) * bytes_per_component,
    };
    expected[1] = {
        .plane = chroma.planes[0],
        .height = chroma_height,
        .minimum_row_bytes =
            static_cast<uint64_t>(chroma_width) * 2u * bytes_per_component,
    };
  }

  const auto objects = base::span(frame.objects).first(frame.object_count);
  for (const auto& object : objects) {
    if (object.size == 0 ||
        object.modifier == gfx::NativePixmapHandle::kNoModifier) {
      return false;
    }
  }

  std::array<bool, T1_MEDIA_MAX_FRAME_OBJECTS> referenced_objects = {};
  for (size_t plane_index = 0; plane_index < expected.size(); ++plane_index) {
    ExpectedPlane& item = expected[plane_index];
    const t1_media_frame_plane& plane = item.plane;
    if (plane.reserved != 0 || plane.object_index >= frame.object_count ||
        plane.pitch == 0 ||
        plane.pitch >
            static_cast<uint32_t>(std::numeric_limits<int32_t>::max()) ||
        plane.pitch < item.minimum_row_bytes ||
        plane.offset >= objects[plane.object_index].size) {
      return false;
    }
    base::CheckedNumeric<uint64_t> required_size = plane.offset;
    required_size +=
        base::CheckedNumeric<uint64_t>(plane.pitch) * (item.height - 1u);
    required_size += item.minimum_row_bytes;
    if (!required_size.AssignIfValid(&item.required_end) ||
        item.required_end > objects[plane.object_index].size) {
      return false;
    }
    for (size_t earlier = 0; earlier < plane_index; ++earlier) {
      const ExpectedPlane& previous = expected[earlier];
      if (previous.plane.object_index == plane.object_index &&
          plane.offset < previous.required_end &&
          previous.plane.offset < item.required_end) {
        return false;
      }
    }
    referenced_objects[plane.object_index] = true;
  }
  return std::all_of(referenced_objects.begin(),
                     referenced_objects.begin() + frame.object_count,
                     [](bool referenced) { return referenced; });
}

bool IsValidT1OSDmaBufObject(int descriptor, uint64_t advertised_size) {
  return IsValidDmaBufObject(descriptor, advertised_size);
}

bool IsValidT1OSLinearMemoryObject(int descriptor, uint64_t advertised_size) {
  struct stat status = {};
  if (descriptor < 0 || advertised_size == 0 ||
      advertised_size > static_cast<uint64_t>(std::numeric_limits<size_t>::max()) ||
      fstat(descriptor, &status) != 0 || !S_ISREG(status.st_mode) ||
      status.st_size < 0 ||
      static_cast<uint64_t>(status.st_size) != advertised_size) {
    return false;
  }
  const int seals = fcntl(descriptor, F_GET_SEALS);
  constexpr int kRequiredSeals =
      F_SEAL_SEAL | F_SEAL_SHRINK | F_SEAL_GROW | F_SEAL_WRITE;
  return seals >= 0 && (seals & kRequiredSeals) == kRequiredSeals;
}

bool IsCurrentT1OSDecoderClient(const T1OSDecoderConnection* source,
                                const T1OSDecoderConnection* current,
                                uint64_t source_epoch,
                                uint64_t current_epoch) {
  return source != nullptr && source == current &&
         source_epoch == current_epoch;
}

bool CanIssueT1OSDecode(size_t in_flight, int maximum_requests) {
  return maximum_requests > 0 &&
         in_flight < base::checked_cast<size_t>(maximum_requests);
}

bool T1OSVideoDecoder::IsAvailable() {
  return T1OSDecoderConnectionPool::GetInstance().IsAvailable();
}

SupportedVideoDecoderConfigs T1OSVideoDecoder::GetSupportedConfigs() {
  return T1OSDecoderConnectionPool::GetInstance().GetSupportedConfigs();
}

std::unique_ptr<VideoDecoder> T1OSVideoDecoder::Create(
    scoped_refptr<base::SequencedTaskRunner> task_runner,
    std::unique_ptr<MediaLog> media_log,
    std::unique_ptr<FrameResourceConverter> frame_converter) {
  scoped_refptr<T1OSDecoderConnection> connection =
      T1OSDecoderConnectionPool::GetInstance().Acquire();
  if (!connection) {
    return nullptr;
  }
  auto decoder = base::WrapUnique(
      new T1OSVideoDecoder(std::move(task_runner), std::move(media_log),
                           std::move(frame_converter), std::move(connection)));
  if (!decoder->AcquireConnection()) {
    return nullptr;
  }
  return decoder;
}

std::unique_ptr<T1OSVideoDecoder> T1OSVideoDecoder::CreateForTesting(
    scoped_refptr<base::SequencedTaskRunner> task_runner,
    std::unique_ptr<MediaLog> media_log,
    std::unique_ptr<FrameResourceConverter> frame_converter,
    scoped_refptr<T1OSDecoderConnection> connection) {
  auto decoder = base::WrapUnique(
      new T1OSVideoDecoder(std::move(task_runner), std::move(media_log),
                           std::move(frame_converter), std::move(connection)));
  if (!decoder->AcquireConnection()) {
    return nullptr;
  }
  return decoder;
}

T1OSVideoDecoder::T1OSVideoDecoder(
    scoped_refptr<base::SequencedTaskRunner> task_runner,
    std::unique_ptr<MediaLog> media_log,
    std::unique_ptr<FrameResourceConverter> frame_converter,
    scoped_refptr<T1OSDecoderConnection> connection)
    : task_runner_(std::move(task_runner)),
      media_log_(std::move(media_log)),
      frame_converter_(std::move(frame_converter)),
      connection_(std::move(connection)) {
  CHECK(task_runner_);
  CHECK(media_log_);
  CHECK(frame_converter_);
  CHECK(connection_);
  DETACH_FROM_SEQUENCE(sequence_checker_);
}

T1OSVideoDecoder::~T1OSVideoDecoder() {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  const bool may_recycle = !failed_ && !init_cb_ && decode_callbacks_.empty() &&
                           !reset_cb_ && !resetting_;
  weak_factory_.InvalidateWeakPtrs();
  if (converter_initialized_) {
    frame_converter_->AbortPendingFrames();
  }
  InitCB init_cb = std::move(init_cb_);
  std::vector<DecodeCB> decode_callbacks = TakePendingDecodes();
  base::OnceClosure reset_cb = std::move(reset_cb_);
  resetting_ = false;
  RetireConnection(may_recycle);
  if (init_cb) {
    std::move(init_cb).Run(DecoderStatus(DecoderStatus::Codes::kAborted));
  }
  for (auto& callback : decode_callbacks) {
    std::move(callback).Run(DecoderStatus(DecoderStatus::Codes::kAborted));
  }
  if (reset_cb) {
    std::move(reset_cb).Run();
  }
}

void T1OSVideoDecoder::Initialize(const VideoDecoderConfig& config,
                                  bool low_delay,
                                  CdmContext* cdm_context,
                                  InitCB init_cb,
                                  const OutputCB& output_cb,
                                  const WaitingCB& waiting_cb) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  if (init_cb_ || !decode_callbacks_.empty() ||
      !pending_credit_decodes_.empty() || resetting_) {
    task_runner_->PostTask(
        FROM_HERE,
        base::BindOnce(std::move(init_cb),
                       DecoderStatus(DecoderStatus::Codes::kFailed)));
    return;
  }

  if (!config.IsValidConfig() || config.is_encrypted() || cdm_context) {
    task_runner_->PostTask(
        FROM_HERE,
        base::BindOnce(
            std::move(init_cb),
            DecoderStatus(config.is_encrypted() || cdm_context
                              ? DecoderStatus::Codes::kUnsupportedEncryptionMode
                              : DecoderStatus::Codes::kUnsupportedConfig)));
    return;
  }
  if (!connection_ ||
      !IsVideoDecoderConfigSupported(
          T1OSConfigsFromCapabilities(connection_->capabilities()), config)) {
    task_runner_->PostTask(
        FROM_HERE,
        base::BindOnce(
            std::move(init_cb),
            DecoderStatus(DecoderStatus::Codes::kUnsupportedProfile)));
    return;
  }

  // Chromium may reinitialize a VideoDecoder for a config change while old
  // output frames remain referenced. Retire the old connection; it stays alive
  // until those SharedImages release, while the new config gets a clean
  // connection from the pool.
  if (create_sent_) {
    RetireConnection(/*may_recycle=*/!failed_);
    if (!AcquireConnection()) {
      task_runner_->PostTask(
          FROM_HERE,
          base::BindOnce(
              std::move(init_cb),
              DecoderStatus(DecoderStatus::Codes::kTooManyDecoders)));
      return;
    }
  }

  config_ = config;
  output_cb_ = output_cb;
  waiting_cb_ = waiting_cb;
  init_cb_ = std::move(init_cb);
  failed_ = false;
  initialized_ = false;

  if (!converter_initialized_) {
    frame_converter_->Initialize(
        task_runner_, base::BindRepeating(&T1OSVideoDecoder::OnConvertedFrame,
                                          weak_factory_.GetWeakPtr()));
    converter_initialized_ = true;
  }
  if (!SendCreate(config, low_delay)) {
    task_runner_->PostTask(
        FROM_HERE,
        base::BindOnce(
            &T1OSVideoDecoder::Fail, weak_factory_.GetWeakPtr(),
            DecoderStatus(DecoderStatus::Codes::kFailedToCreateDecoder)));
  } else {
    ArmOperationTimeout(OperationClass::kCreate, create_request_);
  }
}

void T1OSVideoDecoder::Decode(scoped_refptr<DecoderBuffer> buffer,
                              DecodeCB decode_cb) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  if (!buffer || !initialized_ || resetting_ || failed_ || !connection_) {
    task_runner_->PostTask(
        FROM_HERE,
        base::BindOnce(
            std::move(decode_cb),
            DecoderStatus(buffer ? DecoderStatus::Codes::kNotInitialized
                                 : DecoderStatus::Codes::kInvalidArgument)));
    return;
  }
  const size_t admitted =
      in_flight_decode_requests_ + pending_credit_decodes_.size();
  if (!CanIssueT1OSDecode(admitted, maximum_decode_requests_)) {
    task_runner_->PostTask(
        FROM_HERE,
        base::BindOnce(std::move(decode_cb),
                       DecoderStatus(DecoderStatus::Codes::kFailed)));
    return;
  }

  pending_credit_decodes_.push_back(
      {.buffer = std::move(buffer), .callback = std::move(decode_cb)});
  DrainPendingDecodes();
}

void T1OSVideoDecoder::Reset(base::OnceClosure closure) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  if (resetting_) {
    task_runner_->PostTask(FROM_HERE, std::move(closure));
    return;
  }
  if (!initialized_ || failed_) {
    task_runner_->PostTask(FROM_HERE, std::move(closure));
    return;
  }

  resetting_ = true;
  reset_cb_ = std::move(closure);
  // resetting_ prevents any queued buffer from reaching the wire. RESET_DONE
  // atomically takes both queued and active callbacks, aborts them, and only
  // then runs reset_cb_. This keeps reset ordering and reentrant destruction
  // safe while the native worker may omit an interrupted operation's terminal.
  ++generation_;
  ++operation_epoch_;
  backpressure_request_ = 0;
  if (converter_initialized_) {
    frame_converter_->AbortPendingFrames();
  }
  frame_requests_.clear();
  std::optional<uint64_t> request =
      connection_->Send(T1_MEDIA_RESET, session_, generation_,
                        /*flags=*/0, {});
  if (!request) {
    task_runner_->PostTask(
        FROM_HERE,
        base::BindOnce(&T1OSVideoDecoder::Fail, weak_factory_.GetWeakPtr(),
                       DecoderStatus(DecoderStatus::Codes::kDisconnected)));
    return;
  }
  reset_request_ = *request;
  ArmOperationTimeout(OperationClass::kReset, reset_request_);
}

bool T1OSVideoDecoder::NeedsBitstreamConversion() const {
  // T1MD v1 passes Chromium's demuxed access units and codec extradata
  // unchanged. The native FFmpeg codec context owns format conversion.
  return false;
}

bool T1OSVideoDecoder::CanReadWithoutStalling() const {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return initialized_ && !failed_ && !resetting_ &&
         pending_credit_decodes_.empty() &&
         CanIssueT1OSDecode(in_flight_decode_requests_,
                            maximum_decode_requests_) &&
         connection_ && connection_->HasFrameCredit(in_flight_decode_requests_);
}

int T1OSVideoDecoder::GetMaxDecodeRequests() const {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  return maximum_decode_requests_;
}

bool T1OSVideoDecoder::FramesHoldExternalResources() const {
  // Both output modes retain a service-owned frame slot: DMA-BUF mode until
  // Chromium releases the SharedImage, and diagnostic linear-memory mode until
  // it destroys the mapped VideoFrame. The destruction observer then returns
  // that slot to t1-media-decoderd.
  return true;
}

bool T1OSVideoDecoder::IsPlatformDecoder() const {
  return true;
}

VideoDecoderType T1OSVideoDecoder::GetDecoderType() const {
  return VideoDecoderType::kT1OS;
}

bool T1OSVideoDecoder::SendCreate(const VideoDecoderConfig& config,
                                  bool low_delay) {
  const std::vector<uint8_t>& extradata = config.extra_data();
  const t1_media_capabilities capabilities = connection_->capabilities();
  const uint32_t codec = CodecToT1(config.codec());
  const uint32_t profile = ChromiumProfileToT1OSProfile(config.profile());
  const uint32_t bit_depth = BitDepthForProfile(config.profile());
  if (extradata.size() > capabilities.maximum_extradata_bytes ||
      codec == T1_MEDIA_CODEC_UNKNOWN ||
      profile == T1_MEDIA_PROFILE_UNKNOWN ||
      !CapabilitiesSupportCreate(capabilities, codec, profile, bit_depth)) {
    return false;
  }

  t1_media_create create = {};
  create.codec = codec;
  create.profile = profile;
  create.coded_width =
      base::checked_cast<uint32_t>(config.coded_size().width());
  create.coded_height =
      base::checked_cast<uint32_t>(config.coded_size().height());
  create.visible_x = base::checked_cast<uint32_t>(config.visible_rect().x());
  create.visible_y = base::checked_cast<uint32_t>(config.visible_rect().y());
  create.visible_width =
      base::checked_cast<uint32_t>(config.visible_rect().width());
  create.visible_height =
      base::checked_cast<uint32_t>(config.visible_rect().height());
  create.bit_depth = bit_depth;
  create.chroma_subsampling = T1_MEDIA_CHROMA_420;
  create.color_primaries = PrimaryToT1(config.color_space_info().primaries());
  create.color_transfer = TransferToT1(config.color_space_info().transfer());
  create.color_matrix = MatrixToT1(config.color_space_info().matrix());
  create.color_range = RangeToT1(config.color_space_info().range());
  create.flags = low_delay ? T1_MEDIA_CREATE_LOW_DELAY : 0;
  create.extradata_size = base::checked_cast<uint32_t>(extradata.size());
  // DMA-BUF output is deliberately separate-layer only. Composed NV12/P010
  // is used by the sealed linear-memory diagnostic transport, not advertised
  // as an EGL importer capability.
  create.import_fourcc_count = 6;
  create.import_fourcc[0] = T1_MEDIA_DRM_FORMAT_R8;
  create.import_fourcc[1] = T1_MEDIA_DRM_FORMAT_RG88;
  create.import_fourcc[2] = T1_MEDIA_DRM_FORMAT_GR88;
  create.import_fourcc[3] = T1_MEDIA_DRM_FORMAT_R16;
  create.import_fourcc[4] = T1_MEDIA_DRM_FORMAT_RG1616;
  create.import_fourcc[5] = T1_MEDIA_DRM_FORMAT_GR1616;

  std::vector<uint8_t> payload(sizeof(create) + extradata.size());
  std::copy(base::byte_span_from_ref(create).begin(),
            base::byte_span_from_ref(create).end(), payload.begin());
  if (!extradata.empty()) {
    std::copy(extradata.begin(), extradata.end(),
              payload.begin() + sizeof(create));
  }

  std::optional<uint64_t> request =
      connection_->Send(T1_MEDIA_CREATE, session_, generation_,
                        /*flags=*/0, payload);
  create_sent_ = request.has_value();
  create_request_ = request.value_or(0);
  return create_sent_;
}

std::optional<uint64_t> T1OSVideoDecoder::SendDecodeBuffer(
    const DecoderBuffer& buffer) {
  if (buffer.size() == 0 ||
      buffer.size() > connection_->capabilities().maximum_encoded_bytes) {
    return std::nullopt;
  }
  base::ScopedFD access_unit = CreateSealedAccessUnit(buffer);
  if (!access_unit.is_valid()) {
    return std::nullopt;
  }

  t1_media_decode decode = {};
  decode.timestamp_ns = buffer.timestamp().InNanoseconds();
  decode.duration_ns =
      buffer.duration() == kNoTimestamp ? 0 : buffer.duration().InNanoseconds();
  decode.data_offset = 0;
  decode.data_size = base::checked_cast<uint32_t>(buffer.size());
  decode.flags = buffer.is_key_frame() ? T1_MEDIA_DECODE_KEYFRAME : 0;
  const int descriptor = access_unit.get();
  return connection_->Send(T1_MEDIA_DECODE, session_, generation_,
                           /*flags=*/0, base::byte_span_from_ref(decode),
                           base::span_from_ref(descriptor));
}

void T1OSVideoDecoder::RetireConnection(bool may_recycle) {
  if (!connection_) {
    return;
  }
  ++client_epoch_;
  ++operation_epoch_;
  connection_->ClearClient();
  if (create_sent_ && may_recycle) {
    connection_->BeginRecycle(
        session_, generation_,
        base::BindOnce(
            &T1OSDecoderConnectionPool::Recycle,
            base::Unretained(&T1OSDecoderConnectionPool::GetInstance())));
  } else if (!create_sent_) {
    T1OSDecoderConnectionPool::GetInstance().Recycle(connection_);
  } else {
    // DESTROY is only legal after every earlier operation has completed and
    // every delivered frame has been released. Closing is the fail-safe path
    // for teardown during an outstanding protocol operation or after failure.
    connection_->Abandon();
  }
  connection_.reset();
  create_sent_ = false;
  initialized_ = false;
  frame_requests_.clear();
  flush_request_ = 0;
  backpressure_request_ = 0;
}

bool T1OSVideoDecoder::AcquireConnection() {
  if (!connection_) {
    connection_ = T1OSDecoderConnectionPool::GetInstance().Acquire();
  }
  if (!connection_) {
    return false;
  }
  const uint64_t session = connection_->session();
  if (session == 0) {
    connection_->Abandon();
    connection_.reset();
    return false;
  }
  session_ = session;
  generation_ = 1;
  const uint64_t epoch = ++client_epoch_;
  if (!connection_->SetClient(
          base::BindRepeating(&T1OSVideoDecoder::OnPacket,
                              weak_factory_.GetWeakPtr(), connection_, epoch),
          base::BindOnce(&T1OSVideoDecoder::OnDisconnected,
                         weak_factory_.GetWeakPtr(), connection_, epoch),
          base::BindRepeating(&T1OSVideoDecoder::OnFrameCreditAvailable,
                              weak_factory_.GetWeakPtr(), connection_,
                              epoch))) {
    connection_->Abandon();
    connection_.reset();
    return false;
  }
  return true;
}

void T1OSVideoDecoder::DrainPendingDecodes() {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  while (!failed_ && !resetting_ && connection_ &&
         !pending_credit_decodes_.empty() &&
         CanIssueT1OSDecode(in_flight_decode_requests_,
                            maximum_decode_requests_)) {
    PendingDecode& pending = pending_credit_decodes_.front();
    // A single access unit may produce multiple frames. Keep exactly one
    // native operation outstanding so a RELEASE is never trapped behind
    // already-sent DECODE messages while the worker holds pending output.
    // FLUSH is allowed even when every export slot is occupied: the worker can
    // complete immediately when there is no delayed output, or retain one
    // delayed frame and enter explicit BACKPRESSURE until a RELEASE arrives.
    if (in_flight_decode_requests_ != 0 ||
        (!pending.buffer->end_of_stream() && !connection_->HasFrameCredit())) {
      return;
    }
    std::optional<uint64_t> request;
    if (pending.buffer->end_of_stream()) {
      request = connection_->Send(T1_MEDIA_FLUSH, session_, generation_,
                                  /*flags=*/0, {});
    } else if (!pending.buffer->is_encrypted()) {
      request = SendDecodeBuffer(*pending.buffer);
    }
    if (!request) {
      task_runner_->PostTask(
          FROM_HERE,
          base::BindOnce(
              &T1OSVideoDecoder::Fail, weak_factory_.GetWeakPtr(),
              DecoderStatus(
                  pending.buffer->end_of_stream()
                      ? DecoderStatus::Codes::kDisconnected
                      : DecoderStatus::Codes::kPlatformDecodeFailure)));
      return;
    }
    const bool end_of_stream = pending.buffer->end_of_stream();
    decode_callbacks_.emplace(*request, std::move(pending.callback));
    frame_requests_.insert(*request);
    if (end_of_stream) {
      flush_request_ = *request;
    }
    pending_credit_decodes_.pop_front();
    ++in_flight_decode_requests_;
    ArmOperationTimeout(
        end_of_stream ? OperationClass::kFlush : OperationClass::kDecode,
        *request);
  }
}

void T1OSVideoDecoder::OnFrameCreditAvailable(
    scoped_refptr<T1OSDecoderConnection> source,
    uint64_t client_epoch) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  if (!IsCurrentT1OSDecoderClient(source.get(), connection_.get(), client_epoch,
                                  client_epoch_)) {
    return;
  }
  DrainPendingDecodes();
}

void T1OSVideoDecoder::ArmOperationTimeout(OperationClass operation,
                                           uint64_t request) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  base::TimeDelta timeout;
  switch (operation) {
    case OperationClass::kCreate:
      timeout = kCreateOperationTimeout;
      break;
    case OperationClass::kDecode:
      timeout = kDecodeOperationTimeout;
      break;
    case OperationClass::kFlush:
      timeout = kFlushOperationTimeout;
      break;
    case OperationClass::kReset:
      timeout = kResetOperationTimeout;
      break;
  }
  task_runner_->PostDelayedTask(
      FROM_HERE,
      base::BindOnce(&T1OSVideoDecoder::OnOperationTimeout,
                     weak_factory_.GetWeakPtr(), operation, request,
                     client_epoch_, operation_epoch_),
      timeout);
}

void T1OSVideoDecoder::OnOperationTimeout(OperationClass operation,
                                          uint64_t request,
                                          uint64_t client_epoch,
                                          uint64_t operation_epoch) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  if (failed_ || client_epoch != client_epoch_ ||
      operation_epoch != operation_epoch_) {
    return;
  }
  bool pending = false;
  switch (operation) {
    case OperationClass::kCreate:
      pending = init_cb_ && create_request_ == request;
      break;
    case OperationClass::kDecode:
    case OperationClass::kFlush:
      pending = decode_callbacks_.contains(request);
      break;
    case OperationClass::kReset:
      pending = resetting_ && reset_cb_ && reset_request_ == request;
      break;
  }
  if (!pending) {
    return;
  }
  MEDIA_LOG(ERROR, media_log_)
      << "T1MD operation timed out: class=" << static_cast<int>(operation)
      << " request=" << request;
  Fail(DecoderStatus(DecoderStatus::Codes::kDisconnected));
}

void T1OSVideoDecoder::OnPacket(scoped_refptr<T1OSDecoderConnection> source,
                                uint64_t client_epoch,
                                T1OSDecoderPacket packet) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  if (!IsCurrentT1OSDecoderClient(source.get(), connection_.get(), client_epoch,
                                  client_epoch_)) {
    if (packet.header.type == T1_MEDIA_FRAME &&
        packet.payload.size() == sizeof(t1_media_frame)) {
      t1_media_frame frame = {};
      std::copy(packet.payload.begin(), packet.payload.end(),
                base::byte_span_from_ref(frame).begin());
      if (frame.frame_id == 0) {
        source->Abandon();
      } else if (source->NoteFrameReady()) {
        source->ReleaseFrame(packet.header.session, packet.header.generation,
                             frame.frame_id);
      } else {
        source->ReleaseUntrackedFrame(packet.header.session,
                                      packet.header.generation, frame.frame_id);
        source->Abandon();
      }
    }
    return;
  }
  if (packet.header.session != session_) {
    Fail(DecoderStatus(DecoderStatus::Codes::kFailed));
    return;
  }
  if (failed_) {
    if (packet.header.type == T1_MEDIA_FRAME &&
        packet.payload.size() == sizeof(t1_media_frame)) {
      t1_media_frame frame = {};
      std::copy(packet.payload.begin(), packet.payload.end(),
                base::byte_span_from_ref(frame).begin());
      if (frame.frame_id == 0) {
        connection_->Abandon();
      } else if (connection_->NoteFrameReady()) {
        connection_->ReleaseFrame(packet.header.session,
                                  packet.header.generation, frame.frame_id);
      } else {
        connection_->ReleaseUntrackedFrame(
            packet.header.session, packet.header.generation, frame.frame_id);
        connection_->Abandon();
      }
    }
    return;
  }
  if (packet.header.generation != generation_) {
    if (packet.header.type == T1_MEDIA_FRAME &&
        packet.payload.size() == sizeof(t1_media_frame)) {
      t1_media_frame frame = {};
      std::copy(packet.payload.begin(), packet.payload.end(),
                base::byte_span_from_ref(frame).begin());
      if (frame.frame_id == 0) {
        connection_->Abandon();
      } else if (connection_->NoteFrameReady()) {
        connection_->ReleaseFrame(packet.header.session,
                                  packet.header.generation, frame.frame_id);
      } else {
        connection_->ReleaseUntrackedFrame(
            packet.header.session, packet.header.generation, frame.frame_id);
        connection_->Abandon();
      }
    }
    return;
  }

  switch (packet.header.type) {
    case T1_MEDIA_CREATED:
      OnCreated(packet);
      break;
    case T1_MEDIA_DECODE_DONE:
      OnDecodeDone(packet);
      break;
    case T1_MEDIA_FRAME:
      OnFrame(std::move(packet));
      break;
    case T1_MEDIA_BACKPRESSURE:
      OnBackpressure(packet);
      break;
    case T1_MEDIA_FLUSHED:
      OnFlushed(packet);
      break;
    case T1_MEDIA_RESET_DONE:
      OnResetDone(packet);
      break;
    case T1_MEDIA_ERROR:
      OnServiceError(packet);
      break;
    default:
      Fail(DecoderStatus(DecoderStatus::Codes::kFailed));
      break;
  }
}

void T1OSVideoDecoder::OnCreated(const T1OSDecoderPacket& packet) {
  if (!init_cb_ || packet.header.request != create_request_ ||
      packet.header.flags != 0 ||
      packet.payload.size() != sizeof(t1_media_created) ||
      !packet.descriptors.empty()) {
    Fail(DecoderStatus(DecoderStatus::Codes::kFailedToCreateDecoder));
    return;
  }
  t1_media_created created = {};
  std::copy(packet.payload.begin(), packet.payload.end(),
            base::byte_span_from_ref(created).begin());
  if (created.reserved != 0) {
    Fail(DecoderStatus(DecoderStatus::Codes::kFailedToCreateDecoder));
    return;
  }
  DecoderStatus status = StatusFromT1(created.status, /*initializing=*/true);
  if (status.is_ok()) {
    const t1_media_capabilities capabilities = connection_->capabilities();
    if (created.maximum_decode_requests == 0 ||
        created.maximum_decode_requests >
            capabilities.maximum_decode_requests ||
        created.maximum_in_flight_frames == 0 ||
        created.maximum_in_flight_frames >
            capabilities.maximum_in_flight_frames) {
      Fail(DecoderStatus(DecoderStatus::Codes::kFailedToCreateDecoder));
      return;
    }
    // GetMaxDecodeRequests() is a static Mojo admission limit. Native wire
    // operations are separately serialized by DrainPendingDecodes() so RELEASE
    // can always reach a worker retaining lossless pending output.
    maximum_decode_requests_ =
        base::checked_cast<int>(created.maximum_decode_requests);
    initialized_ = true;
  }
  std::move(init_cb_).Run(std::move(status));
}

void T1OSVideoDecoder::OnDecodeDone(const T1OSDecoderPacket& packet) {
  auto callback = decode_callbacks_.find(packet.header.request);
  if (callback == decode_callbacks_.end() || packet.header.flags != 0 ||
      packet.payload.size() != sizeof(t1_media_decode_done) ||
      !packet.descriptors.empty() || in_flight_decode_requests_ == 0 ||
      flush_request_ == packet.header.request ||
      backpressure_request_ == packet.header.request) {
    Fail(DecoderStatus(DecoderStatus::Codes::kPlatformDecodeFailure));
    return;
  }
  t1_media_decode_done done = {};
  std::copy(packet.payload.begin(), packet.payload.end(),
            base::byte_span_from_ref(done).begin());
  if (done.reserved != 0) {
    Fail(DecoderStatus(DecoderStatus::Codes::kPlatformDecodeFailure));
    return;
  }
  DecodeCB decode_cb = std::move(callback->second);
  decode_callbacks_.erase(callback);
  frame_requests_.erase(packet.header.request);
  --in_flight_decode_requests_;
  task_runner_->PostTask(FROM_HERE,
                         base::BindOnce(&T1OSVideoDecoder::DrainPendingDecodes,
                                        weak_factory_.GetWeakPtr()));
  std::move(decode_cb).Run(StatusFromT1(done.status));
}

void T1OSVideoDecoder::OnFrame(T1OSDecoderPacket packet) {
  if (packet.payload.size() != sizeof(t1_media_frame)) {
    Fail(DecoderStatus(DecoderStatus::Codes::kFailedToGetVideoFrame));
    return;
  }
  t1_media_frame frame = {};
  std::copy(packet.payload.begin(), packet.payload.end(),
            base::byte_span_from_ref(frame).begin());
  if (frame.frame_id == 0) {
    Fail(DecoderStatus(DecoderStatus::Codes::kFailedToGetVideoFrame));
    return;
  }

  // From this point every failure must release the native slot. The converter
  // retains the FrameResource on success, so disarm only after its destruction
  // observer owns the RELEASE.
  if (!connection_->NoteFrameReady()) {
    connection_->ReleaseUntrackedFrame(session_, generation_, frame.frame_id);
    connection_->Abandon();
    Fail(DecoderStatus(DecoderStatus::Codes::kFailedToGetVideoFrame));
    return;
  }
  base::ScopedClosureRunner release_frame(
      base::BindOnce(&T1OSDecoderConnection::ReleaseFrame, connection_,
                     session_, generation_, frame.frame_id));

  if (backpressure_request_ != 0 ||
      !frame_requests_.contains(packet.header.request) ||
      packet.header.flags != 0 ||
      !ValidateT1OSFrameLayout(frame, packet.descriptors.size())) {
    Fail(DecoderStatus(DecoderStatus::Codes::kFailedToGetVideoFrame));
    return;
  }

  VideoPixelFormat pixel_format = PIXEL_FORMAT_UNKNOWN;
  if (frame.pixel_format == T1_MEDIA_PIXEL_FORMAT_NV12) {
    if (frame.bit_depth != 8) {
      Fail(DecoderStatus(DecoderStatus::Codes::kFailedToGetVideoFrame));
      return;
    }
    pixel_format = PIXEL_FORMAT_NV12;
  } else if (frame.pixel_format == T1_MEDIA_PIXEL_FORMAT_P010) {
    if (frame.bit_depth != 10) {
      Fail(DecoderStatus(DecoderStatus::Codes::kFailedToGetVideoFrame));
      return;
    }
    pixel_format = PIXEL_FORMAT_P010LE;
  } else {
    Fail(DecoderStatus(DecoderStatus::Codes::kFailedToGetVideoFrame));
    return;
  }

  struct ExpectedPlane {
    t1_media_frame_plane plane;
    uint32_t height;
    uint64_t minimum_row_bytes;
    uint64_t required_end = 0;
  };
  std::vector<ExpectedPlane> expected_wire_planes;
  const uint32_t chroma_width = frame.coded_width / 2 + frame.coded_width % 2;
  const uint32_t chroma_height =
      frame.coded_height / 2 + frame.coded_height % 2;
  const uint64_t bytes_per_component =
      frame.pixel_format == T1_MEDIA_PIXEL_FORMAT_NV12 ? 1u : 2u;
  const bool separate_layers =
      (frame.flags & T1_MEDIA_FRAME_SEPARATE_LAYERS) != 0;
  bool chroma_is_drm_rg = false;
  if (!separate_layers) {
    const auto& layer = frame.layers[0];
    const uint32_t composed_format =
        frame.pixel_format == T1_MEDIA_PIXEL_FORMAT_NV12
            ? T1_MEDIA_DRM_FORMAT_NV12
            : T1_MEDIA_DRM_FORMAT_P010;
    if (frame.layer_count != 1 || layer.drm_fourcc != composed_format ||
        layer.width != frame.coded_width ||
        layer.height != frame.coded_height || layer.plane_count != 2) {
      Fail(DecoderStatus(DecoderStatus::Codes::kFailedToGetVideoFrame));
      return;
    }
    expected_wire_planes = {
        {layer.planes[0], frame.coded_height,
         static_cast<uint64_t>(frame.coded_width) * bytes_per_component},
        {layer.planes[1], chroma_height,
         static_cast<uint64_t>(chroma_width) * 2u * bytes_per_component},
    };
  } else {
    const auto& luma = frame.layers[0];
    const auto& chroma = frame.layers[1];
    const uint32_t luma_format =
        frame.pixel_format == T1_MEDIA_PIXEL_FORMAT_NV12
            ? T1_MEDIA_DRM_FORMAT_R8
            : T1_MEDIA_DRM_FORMAT_R16;
    const uint32_t chroma_format =
        frame.pixel_format == T1_MEDIA_PIXEL_FORMAT_NV12
            ? T1_MEDIA_DRM_FORMAT_RG88
            : T1_MEDIA_DRM_FORMAT_RG1616;
    const uint32_t alternate_chroma_format =
        frame.pixel_format == T1_MEDIA_PIXEL_FORMAT_NV12
            ? T1_MEDIA_DRM_FORMAT_GR88
            : T1_MEDIA_DRM_FORMAT_GR1616;
    if (frame.layer_count != 2 || luma.drm_fourcc != luma_format ||
        (chroma.drm_fourcc != chroma_format &&
         chroma.drm_fourcc != alternate_chroma_format) ||
        luma.width != frame.coded_width ||
        luma.height != frame.coded_height || luma.plane_count != 1 ||
        chroma.width != chroma_width || chroma.height != chroma_height ||
        chroma.plane_count != 1) {
      Fail(DecoderStatus(DecoderStatus::Codes::kFailedToGetVideoFrame));
      return;
    }
    expected_wire_planes = {
        {luma.planes[0], frame.coded_height,
         static_cast<uint64_t>(frame.coded_width) * bytes_per_component},
        {chroma.planes[0], chroma_height,
         static_cast<uint64_t>(chroma_width) * 2u * bytes_per_component},
    };
    chroma_is_drm_rg = chroma.drm_fourcc == chroma_format;
  }
  const size_t expected_planes = VideoFrame::NumPlanes(pixel_format);
  if (expected_wire_planes.size() != expected_planes) {
    Fail(DecoderStatus(DecoderStatus::Codes::kFailedToGetVideoFrame));
    return;
  }

  const auto objects = base::span(frame.objects).first(frame.object_count);
  const uint64_t modifier = objects.front().modifier;
  const bool linear_memory =
      (frame.flags & T1_MEDIA_FRAME_LINEAR_MEMORY) != 0;
  for (size_t object_index = 0; object_index < frame.object_count;
       ++object_index) {
    if (objects[object_index].size == 0 ||
        objects[object_index].modifier ==
            gfx::NativePixmapHandle::kNoModifier ||
        (linear_memory
             ? !IsValidT1OSLinearMemoryObject(
                   packet.descriptors[object_index].get(),
                   objects[object_index].size)
             : !IsValidT1OSDmaBufObject(
                   packet.descriptors[object_index].get(),
                   objects[object_index].size))) {
      Fail(DecoderStatus(DecoderStatus::Codes::kFailedToGetVideoFrame));
      return;
    }
  }

  std::vector<ColorPlaneLayout> plane_layouts;
  std::vector<base::ScopedFD> plane_descriptors;
  std::vector<uint64_t> plane_modifiers;
  std::array<bool, T1_MEDIA_MAX_FRAME_OBJECTS> referenced_objects = {};
  plane_layouts.reserve(expected_planes);
  plane_descriptors.reserve(expected_planes);
  plane_modifiers.reserve(expected_planes);
  for (size_t plane_index = 0; plane_index < expected_wire_planes.size();
       ++plane_index) {
    ExpectedPlane& expected = expected_wire_planes[plane_index];
    const auto& plane = expected.plane;
    if (plane.object_index >= frame.object_count || plane.pitch == 0 ||
        plane.pitch >
            static_cast<uint32_t>(std::numeric_limits<int32_t>::max()) ||
        plane.pitch < expected.minimum_row_bytes ||
        plane.offset >= objects[plane.object_index].size) {
      Fail(DecoderStatus(DecoderStatus::Codes::kFailedToGetVideoFrame));
      return;
    }
    base::CheckedNumeric<uint64_t> required_size = plane.offset;
    required_size +=
        base::CheckedNumeric<uint64_t>(plane.pitch) * (expected.height - 1u);
    required_size += expected.minimum_row_bytes;
    uint64_t required_size_value = 0;
    if (!required_size.AssignIfValid(&required_size_value) ||
        required_size_value > objects[plane.object_index].size) {
      Fail(DecoderStatus(DecoderStatus::Codes::kFailedToGetVideoFrame));
      return;
    }
    expected.required_end = required_size_value;
    for (size_t earlier = 0; earlier < plane_index; ++earlier) {
      const ExpectedPlane& previous = expected_wire_planes[earlier];
      if (previous.plane.object_index == plane.object_index &&
          plane.offset < previous.required_end &&
          previous.plane.offset < expected.required_end) {
        Fail(DecoderStatus(DecoderStatus::Codes::kFailedToGetVideoFrame));
        return;
      }
    }
    referenced_objects[plane.object_index] = true;
    plane_layouts.emplace_back(plane.pitch, plane.offset,
                               expected.required_end - plane.offset);
    plane_modifiers.push_back(objects[plane.object_index].modifier);
    if (!linear_memory) {
      plane_descriptors.emplace_back(
          HANDLE_EINTR(dup(packet.descriptors[plane.object_index].get())));
      if (!plane_descriptors.back().is_valid()) {
        Fail(DecoderStatus(DecoderStatus::Codes::kFailedToGetVideoFrame));
        return;
      }
    }
  }
  for (size_t object_index = 0; object_index < frame.object_count;
       ++object_index) {
    if (!referenced_objects[object_index]) {
      Fail(DecoderStatus(DecoderStatus::Codes::kFailedToGetVideoFrame));
      return;
    }
  }

  gfx::Size coded_size(base::checked_cast<int>(frame.coded_width),
                       base::checked_cast<int>(frame.coded_height));
  gfx::Rect visible_rect(base::checked_cast<int>(frame.visible_x),
                         base::checked_cast<int>(frame.visible_y),
                         base::checked_cast<int>(frame.visible_width),
                         base::checked_cast<int>(frame.visible_height));
  if (visible_rect.IsEmpty() || !gfx::Rect(coded_size).Contains(visible_rect)) {
    Fail(DecoderStatus(DecoderStatus::Codes::kFailedToGetVideoFrame));
    return;
  }
  gfx::Size natural_size = config_.visible_rect().size() == visible_rect.size()
                               ? config_.natural_size()
                               : visible_rect.size();

  auto layout = VideoFrameLayout::CreateWithPlanes(
      pixel_format, coded_size, std::move(plane_layouts),
      VideoFrameLayout::kBufferAddressAlignment, modifier);
  if (!layout) {
    Fail(DecoderStatus(DecoderStatus::Codes::kFailedToGetVideoFrame));
    return;
  }
  if (linear_memory) {
    const size_t mapping_size =
        base::checked_cast<size_t>(objects.front().size);
    void* mapping = mmap(nullptr, mapping_size, PROT_READ, MAP_SHARED,
                         packet.descriptors.front().get(), 0);
    if (mapping == MAP_FAILED) {
      PLOG(ERROR) << "T1OS_MEDIA_DECODER linear-memory mmap failed";
      Fail(DecoderStatus(DecoderStatus::Codes::kFailedToGetVideoFrame));
      return;
    }
    scoped_refptr<VideoFrame> linear_frame =
        VideoFrame::WrapExternalDataWithLayout(
            *layout, visible_rect, natural_size,
            UNSAFE_BUFFERS(base::span(
                static_cast<const uint8_t*>(mapping), mapping_size)),
            base::Nanoseconds(frame.timestamp_ns));
    if (!linear_frame) {
      munmap(mapping, mapping_size);
      Fail(DecoderStatus(DecoderStatus::Codes::kFailedToGetVideoFrame));
      return;
    }
    linear_frame->metadata().power_efficient = true;
    if (frame.duration_ns > 0) {
      linear_frame->metadata().frame_duration =
          base::Nanoseconds(frame.duration_ns);
    }
    VideoColorSpace frame_color_space;
    if (!ColorSpaceFromT1(frame, config_.color_space_info(),
                          &frame_color_space)) {
      munmap(mapping, mapping_size);
      Fail(DecoderStatus(DecoderStatus::Codes::kFailedToGetVideoFrame));
      return;
    }
    linear_frame->set_color_space(
        frame_color_space.GuessGfxColorSpace());
    linear_frame->set_hdr_metadata(config_.hdr_metadata());
    linear_frame->AddDestructionObserver(base::BindOnce(
        [](void* address, size_t size) { munmap(address, size); },
        mapping, mapping_size));
    linear_frame->AddDestructionObserver(
        base::BindOnce(&T1OSDecoderConnection::ReleaseFrame, connection_,
                       session_, generation_, frame.frame_id));
    (void)release_frame.Release();
    LOG(INFO) << "T1OS_MEDIA_DECODER output=linear-memory "
              << "format=" << VideoPixelFormatToString(pixel_format)
              << " size=" << coded_size.ToString();
    output_cb_.Run(std::move(linear_frame));
    return;
  }
  scoped_refptr<NativePixmapFrameResource> resource =
      NativePixmapFrameResource::CreateForT1OS(
          *layout, visible_rect, natural_size,
          std::move(plane_descriptors), std::move(plane_modifiers),
          base::Nanoseconds(frame.timestamp_ns), chroma_is_drm_rg);
  if (!resource) {
    Fail(DecoderStatus(DecoderStatus::Codes::kFailedToGetVideoFrame));
    return;
  }

  resource->metadata().power_efficient = true;
  if (frame.duration_ns > 0) {
    resource->metadata().frame_duration = base::Nanoseconds(frame.duration_ns);
  }
  VideoColorSpace frame_color_space;
  if (!ColorSpaceFromT1(frame, config_.color_space_info(),
                        &frame_color_space)) {
    Fail(DecoderStatus(DecoderStatus::Codes::kFailedToGetVideoFrame));
    return;
  }
  resource->set_color_space(frame_color_space.GuessGfxColorSpace());
  resource->set_hdr_metadata(config_.hdr_metadata());

  resource->AddDestructionObserver(
      base::BindOnce(&T1OSDecoderConnection::ReleaseFrame, connection_,
                     session_, generation_, frame.frame_id));
  (void)release_frame.Release();
  frame_converter_->ConvertFrame(std::move(resource));
}

void T1OSVideoDecoder::OnBackpressure(const T1OSDecoderPacket& packet) {
  if (packet.header.flags != 0 || !packet.descriptors.empty() ||
      packet.payload.size() != sizeof(t1_media_backpressure) ||
      !decode_callbacks_.contains(packet.header.request) ||
      !frame_requests_.contains(packet.header.request)) {
    Fail(DecoderStatus(DecoderStatus::Codes::kPlatformDecodeFailure));
    return;
  }

  t1_media_backpressure backpressure = {};
  std::copy(packet.payload.begin(), packet.payload.end(),
            base::byte_span_from_ref(backpressure).begin());
  const uint32_t maximum_frames =
      connection_->capabilities().maximum_in_flight_frames;
  if (backpressure.state == T1_MEDIA_BACKPRESSURE_ENTER) {
    // ENTER is meaningful only when every exported surface slot is occupied.
    // A local RELEASE may race packet delivery, so validate the wire snapshot
    // against the negotiated maximum rather than mutable local frame count.
    if (backpressure_request_ != 0 || maximum_frames == 0 ||
        backpressure.in_flight_frames != maximum_frames) {
      Fail(DecoderStatus(DecoderStatus::Codes::kPlatformDecodeFailure));
      return;
    }
    backpressure_request_ = packet.header.request;
    ++operation_epoch_;
    return;
  }

  if (backpressure.state != T1_MEDIA_BACKPRESSURE_EXIT ||
      backpressure_request_ != packet.header.request || maximum_frames == 0 ||
      backpressure.in_flight_frames >= maximum_frames) {
    Fail(DecoderStatus(DecoderStatus::Codes::kPlatformDecodeFailure));
    return;
  }
  backpressure_request_ = 0;
  ++operation_epoch_;
  ArmOperationTimeout(flush_request_ == packet.header.request
                          ? OperationClass::kFlush
                          : OperationClass::kDecode,
                      packet.header.request);
}

void T1OSVideoDecoder::OnFlushed(const T1OSDecoderPacket& packet) {
  auto callback = decode_callbacks_.find(packet.header.request);
  uint32_t status = T1_MEDIA_STATUS_PROTOCOL_ERROR;
  if (callback == decode_callbacks_.end() || packet.header.flags != 0 ||
      !ParseResult(packet, &status) || in_flight_decode_requests_ == 0 ||
      flush_request_ != packet.header.request ||
      backpressure_request_ == packet.header.request) {
    Fail(DecoderStatus(DecoderStatus::Codes::kPlatformDecodeFailure));
    return;
  }
  DecodeCB decode_cb = std::move(callback->second);
  decode_callbacks_.erase(callback);
  frame_requests_.erase(packet.header.request);
  flush_request_ = 0;
  --in_flight_decode_requests_;
  task_runner_->PostTask(FROM_HERE,
                         base::BindOnce(&T1OSVideoDecoder::DrainPendingDecodes,
                                        weak_factory_.GetWeakPtr()));
  std::move(decode_cb).Run(StatusFromT1(status));
}

void T1OSVideoDecoder::OnResetDone(const T1OSDecoderPacket& packet) {
  uint32_t status = T1_MEDIA_STATUS_PROTOCOL_ERROR;
  if (!resetting_ || packet.header.request != reset_request_ ||
      packet.header.flags != 0 || !ParseResult(packet, &status)) {
    Fail(DecoderStatus(DecoderStatus::Codes::kPlatformDecodeFailure));
    return;
  }
  DecoderStatus decoder_status = StatusFromT1(status);
  if (!decoder_status.is_ok()) {
    Fail(std::move(decoder_status));
    return;
  }
  std::vector<DecodeCB> decode_callbacks = TakePendingDecodes();
  frame_requests_.clear();
  resetting_ = false;
  reset_request_ = 0;
  base::OnceClosure reset_cb = std::move(reset_cb_);
  for (auto& callback : decode_callbacks) {
    std::move(callback).Run(DecoderStatus(DecoderStatus::Codes::kAborted));
  }
  if (reset_cb) {
    std::move(reset_cb).Run();
  }
}

void T1OSVideoDecoder::OnServiceError(const T1OSDecoderPacket& packet) {
  if (packet.header.flags != 0 || !packet.descriptors.empty() ||
      packet.payload.size() < sizeof(t1_media_error)) {
    Fail(DecoderStatus(DecoderStatus::Codes::kFailed));
    return;
  }
  t1_media_error error = {};
  std::copy_n(packet.payload.begin(), sizeof(error),
              base::byte_span_from_ref(error).begin());
  if (error.detail_size > T1_MEDIA_MAX_ERROR_TEXT ||
      packet.payload.size() != sizeof(error) + error.detail_size) {
    Fail(DecoderStatus(DecoderStatus::Codes::kFailed));
    return;
  }
  const base::span<const char> detail_bytes =
      base::as_chars(base::span(packet.payload).subspan(sizeof(error)));
  std::string detail(detail_bytes.begin(), detail_bytes.end());
  MEDIA_LOG(ERROR, media_log_) << "T1MD service error: " << detail;
  Fail(StatusFromT1(error.status, !initialized_));
}

void T1OSVideoDecoder::OnDisconnected(
    scoped_refptr<T1OSDecoderConnection> source,
    uint64_t client_epoch) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  if (!IsCurrentT1OSDecoderClient(source.get(), connection_.get(), client_epoch,
                                  client_epoch_)) {
    return;
  }
  Fail(DecoderStatus(DecoderStatus::Codes::kDisconnected));
}

void T1OSVideoDecoder::OnConvertedFrame(scoped_refptr<VideoFrame> frame) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  if (!frame) {
    Fail(DecoderStatus(DecoderStatus::Codes::kFailedToGetVideoFrame));
    return;
  }
  frame->metadata().power_efficient = true;
  output_cb_.Run(std::move(frame));
}

void T1OSVideoDecoder::Fail(DecoderStatus status) {
  DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
  if (failed_) {
    return;
  }
  failed_ = true;
  initialized_ = false;
  MEDIA_LOG(ERROR, media_log_) << "T1OSVideoDecoder failed: " << status;
  InitCB init_cb = std::move(init_cb_);
  std::vector<DecodeCB> decode_callbacks = TakePendingDecodes();
  base::OnceClosure reset_cb = std::move(reset_cb_);
  frame_requests_.clear();
  resetting_ = false;
  reset_request_ = 0;
  ++client_epoch_;
  ++operation_epoch_;
  if (connection_) {
    connection_->Abandon();
  }
  if (converter_initialized_) {
    frame_converter_->AbortPendingFrames();
  }
  if (init_cb) {
    std::move(init_cb).Run(status);
  }
  for (auto& callback : decode_callbacks) {
    std::move(callback).Run(status);
  }
  if (reset_cb) {
    std::move(reset_cb).Run();
  }
}

std::vector<VideoDecoder::DecodeCB> T1OSVideoDecoder::TakePendingDecodes() {
  std::vector<DecodeCB> callbacks;
  callbacks.reserve(decode_callbacks_.size() + pending_credit_decodes_.size());
  for (auto& [request, callback] : decode_callbacks_) {
    callbacks.push_back(std::move(callback));
  }
  decode_callbacks_.clear();
  while (!pending_credit_decodes_.empty()) {
    callbacks.push_back(std::move(pending_credit_decodes_.front().callback));
    pending_credit_decodes_.pop_front();
  }
  frame_requests_.clear();
  in_flight_decode_requests_ = 0;
  flush_request_ = 0;
  backpressure_request_ = 0;
  return callbacks;
}

void T1OSVideoDecoder::AbortPendingDecodes() {
  std::vector<DecodeCB> callbacks = TakePendingDecodes();
  for (auto& callback : callbacks) {
    std::move(callback).Run(DecoderStatus(DecoderStatus::Codes::kAborted));
  }
}

uint32_t ChromiumProfileToT1OSProfile(VideoCodecProfile profile) {
  switch (profile) {
    case H264PROFILE_BASELINE:
      return T1_MEDIA_PROFILE_H264_BASELINE;
    case H264PROFILE_MAIN:
      return T1_MEDIA_PROFILE_H264_MAIN;
    case H264PROFILE_HIGH:
      return T1_MEDIA_PROFILE_H264_HIGH;
    case VP8PROFILE_ANY:
      return T1_MEDIA_PROFILE_VP8_ANY;
    case VP9PROFILE_PROFILE0:
      return T1_MEDIA_PROFILE_VP9_0;
    case VP9PROFILE_PROFILE1:
      return T1_MEDIA_PROFILE_VP9_1;
    case VP9PROFILE_PROFILE2:
      return T1_MEDIA_PROFILE_VP9_2;
    case VP9PROFILE_PROFILE3:
      return T1_MEDIA_PROFILE_VP9_3;
    case HEVCPROFILE_MAIN:
      return T1_MEDIA_PROFILE_HEVC_MAIN;
    case HEVCPROFILE_MAIN10:
      return T1_MEDIA_PROFILE_HEVC_MAIN10;
    case AV1PROFILE_PROFILE_MAIN:
      return T1_MEDIA_PROFILE_AV1_MAIN;
    default:
      return T1_MEDIA_PROFILE_UNKNOWN;
  }
}

}  // namespace media
