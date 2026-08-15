// Copyright 2026 The One OS Authors
// Use of this source code is governed by a BSD-style license.

#include "media/gpu/t1os/t1os_video_decoder.h"

#include <fcntl.h>
#include <linux/memfd.h>
#include <poll.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <unistd.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <cstring>
#include <optional>
#include <set>
#include <thread>
#include <utility>
#include <vector>

#include "base/check.h"
#include "base/compiler_specific.h"
#include "base/containers/span.h"
#include "base/files/scoped_file.h"
#include "base/files/scoped_temp_dir.h"
#include "base/functional/callback.h"
#include "base/memory/ptr_util.h"
#include "base/memory/scoped_refptr.h"
#include "base/posix/eintr_wrapper.h"
#include "base/synchronization/waitable_event.h"
#include "base/task/sequenced_task_runner.h"
#include "base/test/bind.h"
#include "base/test/task_environment.h"
#include "base/test/test_timeouts.h"
#include "base/threading/platform_thread.h"
#include "base/time/time.h"
#include "base/time/time_override.h"
#include "media/base/media_util.h"
#include "media/base/t1os_media_switches.h"
#include "media/base/video_color_space.h"
#include "media/gpu/chromeos/frame_resource.h"
#include "media/gpu/chromeos/native_pixmap_frame_resource.h"
#include "media/gpu/t1os/t1_media_decode_protocol.h"
#include "media/gpu/t1os/t1os_decoder_connection.h"
#include "testing/gtest/include/gtest/gtest.h"

namespace media {

class T1OSDecoderConnectionTestPeer {
 public:
  static void MakeRecycleEligibleWithoutStartingDestroy(
      T1OSDecoderConnection* connection) {
    base::AutoLock lock(connection->state_lock_);
    CHECK_EQ(connection->in_flight_frames_, 1u);
    connection->in_flight_frames_ = 0;
  }

  static void MaybeStartDestroy(T1OSDecoderConnection* connection) {
    connection->MaybeStartDestroy();
  }
};

class T1OSVideoDecoderTestPeer {
 public:
  static bool IsBackpressured(const T1OSVideoDecoder* decoder) {
    return decoder->backpressure_request_ != 0;
  }
};

namespace {

constexpr uint64_t kInitialSession = 41;

struct ConnectionPair {
  scoped_refptr<T1OSDecoderConnection> connection;
  base::ScopedFD service_socket;
};

class FakeFrameResourceConverter : public FrameResourceConverter {
 public:
  static std::unique_ptr<FrameResourceConverter> Create() {
    return base::WrapUnique<FrameResourceConverter>(
        new FakeFrameResourceConverter());
  }

 private:
  FakeFrameResourceConverter() = default;
  ~FakeFrameResourceConverter() override = default;

  void ConvertFrameImpl(scoped_refptr<FrameResource> frame) override {
    Output(nullptr);
  }
};

t1_media_capabilities ValidCapabilities() {
  t1_media_capabilities capabilities = {};
  capabilities.features =
      T1_MEDIA_FEATURE_DMABUF | T1_MEDIA_FEATURE_SEALED_INPUT |
      T1_MEDIA_FEATURE_RESET | T1_MEDIA_FEATURE_BACKPRESSURE |
      T1_MEDIA_FEATURE_LINEAR_MEMORY_OUTPUT;
  capabilities.maximum_sessions = kT1OSMediaDecodeDescriptorPoolSize;
  capabilities.maximum_decode_requests = 1;
  capabilities.maximum_in_flight_frames = 2;
  capabilities.maximum_encoded_bytes = 1024 * 1024;
  capabilities.maximum_extradata_bytes = 4096;
  capabilities.profile_count = 1;
  capabilities.profiles[0] = {
      .codec = T1_MEDIA_CODEC_H264,
      .profile = T1_MEDIA_PROFILE_H264_BASELINE,
      .bit_depths = T1_MEDIA_BIT_DEPTH_8,
      .output_formats = T1_MEDIA_OUTPUT_NV12,
      .minimum_width = 16,
      .minimum_height = 16,
      .maximum_width = 4096,
      .maximum_height = 4096,
  };
  return capabilities;
}

bool ReceiveHeader(int socket, t1_media_message_header* header) {
  std::array<uint8_t, T1_MEDIA_MAX_CONTROL_BYTES> bytes = {};
  const ssize_t received =
      HANDLE_EINTR(recv(socket, bytes.data(), bytes.size(), 0));
  if (received < static_cast<ssize_t>(sizeof(*header))) {
    return false;
  }
  std::copy_n(bytes.begin(), sizeof(*header),
              base::byte_span_from_ref(*header).begin());
  return header->magic == T1_MEDIA_PROTOCOL_MAGIC &&
         header->version == T1_MEDIA_PROTOCOL_VERSION &&
         header->size == static_cast<uint32_t>(received);
}

bool ReceiveCreate(int socket,
                   t1_media_message_header* header,
                   t1_media_create* create) {
  std::array<uint8_t, T1_MEDIA_MAX_CONTROL_BYTES> bytes = {};
  const ssize_t received =
      HANDLE_EINTR(recv(socket, bytes.data(), bytes.size(), 0));
  if (received <
      static_cast<ssize_t>(sizeof(*header) + sizeof(*create))) {
    return false;
  }
  std::copy_n(bytes.begin(), sizeof(*header),
              base::byte_span_from_ref(*header).begin());
  std::copy_n(bytes.begin() + sizeof(*header), sizeof(*create),
              base::byte_span_from_ref(*create).begin());
  return header->magic == T1_MEDIA_PROTOCOL_MAGIC &&
         header->version == T1_MEDIA_PROTOCOL_VERSION &&
         header->type == T1_MEDIA_CREATE &&
         header->size == static_cast<uint32_t>(received);
}

bool SendWirePacket(int socket,
                    uint16_t type,
                    uint64_t session,
                    uint64_t request,
                    uint64_t generation,
                    base::span<const uint8_t> payload = {},
                    base::span<const int> descriptors = {}) {
  if (descriptors.size() > 1) {
    return false;
  }
  t1_media_message_header header = {
      .magic = T1_MEDIA_PROTOCOL_MAGIC,
      .version = T1_MEDIA_PROTOCOL_VERSION,
      .type = type,
      .size = static_cast<uint32_t>(sizeof(header) + payload.size()),
      .session = session,
      .request = request,
      .generation = generation,
      .flags = 0,
  };
  std::array<iovec, 2> vectors = {
      iovec{.iov_base = &header, .iov_len = sizeof(header)},
      iovec{.iov_base = const_cast<uint8_t*>(payload.data()),
            .iov_len = payload.size()},
  };
  std::array<uint8_t, CMSG_SPACE(sizeof(int))> control = {};
  msghdr message = {};
  message.msg_iov = vectors.data();
  message.msg_iovlen = payload.empty() ? 1 : 2;
  if (!descriptors.empty()) {
    message.msg_control = control.data();
    message.msg_controllen = control.size();
    cmsghdr* cmsg = CMSG_FIRSTHDR(&message);
    cmsg->cmsg_level = SOL_SOCKET;
    cmsg->cmsg_type = SCM_RIGHTS;
    cmsg->cmsg_len = CMSG_LEN(sizeof(int));
    UNSAFE_BUFFERS(
        std::memcpy(CMSG_DATA(cmsg), descriptors.data(), sizeof(int)));
  }
  return HANDLE_EINTR(sendmsg(socket, &message, MSG_NOSIGNAL | MSG_DONTWAIT)) ==
         static_cast<ssize_t>(header.size);
}

bool WaitForPeerClose(int socket) {
  pollfd event = {
      .fd = socket,
      .events = POLLIN | POLLHUP | POLLERR,
      .revents = 0,
  };
  const int result = HANDLE_EINTR(poll(&event, 1, 2000));
  if (result <= 0) {
    return false;
  }
  if ((event.revents & (POLLHUP | POLLERR)) != 0) {
    return true;
  }
  std::array<uint8_t, 1> byte = {};
  return HANDLE_EINTR(recv(socket, byte.data(), byte.size(), MSG_DONTWAIT)) ==
         0;
}

t1_media_frame ValidNV12Frame() {
  t1_media_frame frame = {};
  frame.frame_id = 7;
  frame.coded_width = 64;
  frame.coded_height = 64;
  frame.visible_width = 64;
  frame.visible_height = 64;
  frame.pixel_format = T1_MEDIA_PIXEL_FORMAT_NV12;
  frame.bit_depth = 8;
  frame.chroma_location = T1_MEDIA_CHROMA_LOCATION_LEFT;
  frame.object_count = 1;
  frame.layer_count = 1;
  frame.flags =
      T1_MEDIA_FRAME_SYNCHRONIZED | T1_MEDIA_FRAME_LINEAR_MEMORY;
  frame.objects[0] = {.size = 6144, .modifier = 0};
  frame.layers[0].drm_fourcc = T1_MEDIA_DRM_FORMAT_NV12;
  frame.layers[0].width = 64;
  frame.layers[0].height = 64;
  frame.layers[0].plane_count = 2;
  frame.layers[0].planes[0] = {
      .object_index = 0,
      .offset = 0,
      .pitch = 64,
      .reserved = 0,
  };
  frame.layers[0].planes[1] = {
      .object_index = 0,
      .offset = 4096,
      .pitch = 64,
      .reserved = 0,
  };
  return frame;
}

t1_media_frame ValidSeparateNV12Frame(uint32_t chroma_fourcc) {
  t1_media_frame frame = ValidNV12Frame();
  frame.object_count = 2;
  frame.layer_count = 2;
  frame.flags =
      T1_MEDIA_FRAME_SYNCHRONIZED | T1_MEDIA_FRAME_SEPARATE_LAYERS;
  frame.objects[0] = {.size = 4096, .modifier = 0};
  frame.objects[1] = {.size = 2048, .modifier = 0};
  frame.layers[0] = {};
  frame.layers[0].drm_fourcc = T1_MEDIA_DRM_FORMAT_R8;
  frame.layers[0].width = 64;
  frame.layers[0].height = 64;
  frame.layers[0].plane_count = 1;
  frame.layers[0].planes[0] = {
      .object_index = 0,
      .offset = 0,
      .pitch = 64,
      .reserved = 0,
  };
  frame.layers[1] = {};
  frame.layers[1].drm_fourcc = chroma_fourcc;
  frame.layers[1].width = 32;
  frame.layers[1].height = 32;
  frame.layers[1].plane_count = 1;
  frame.layers[1].planes[0] = {
      .object_index = 1,
      .offset = 0,
      .pitch = 64,
      .reserved = 0,
  };
  return frame;
}

VideoDecoderConfig ValidDecoderConfig() {
  const gfx::Size coded_size(64, 64);
  return VideoDecoderConfig(VideoCodec::kH264, H264PROFILE_BASELINE,
                            VideoDecoderConfig::AlphaMode::kIsOpaque,
                            VideoColorSpace(), kNoTransformation, coded_size,
                            gfx::Rect(coded_size), coded_size,
                            /*extra_data=*/{}, EncryptionScheme::kUnencrypted);
}

VideoDecoderConfig ValidAV1DecoderConfig() {
  const gfx::Size coded_size(64, 64);
  return VideoDecoderConfig(VideoCodec::kAV1, AV1PROFILE_PROFILE_MAIN,
                            VideoDecoderConfig::AlphaMode::kIsOpaque,
                            VideoColorSpace(), kNoTransformation, coded_size,
                            gfx::Rect(coded_size), coded_size,
                            /*extra_data=*/{}, EncryptionScheme::kUnencrypted);
}

class T1OSVideoDecoderTest : public testing::Test {
 protected:
  ConnectionPair Connect(const t1_media_capabilities& capabilities,
                         bool expect_success = true) {
    std::array<int, 2> sockets = {-1, -1};
    CHECK_EQ(
        socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0, sockets.data()),
        0);
    ConnectionPair pair = {
        .connection = base::MakeRefCounted<T1OSDecoderConnection>(
            base::ScopedFD(sockets[0]),
            base::SequencedTaskRunner::GetCurrentDefault()),
        .service_socket = base::ScopedFD(sockets[1]),
    };
    std::atomic<bool> service_ok = true;
    std::thread service(
        [socket = pair.service_socket.get(), &capabilities, &service_ok]() {
          t1_media_message_header hello = {};
          if (!ReceiveHeader(socket, &hello) || hello.type != T1_MEDIA_HELLO ||
              !SendWirePacket(socket, T1_MEDIA_CAPABILITIES, kInitialSession,
                              hello.request, 0,
                              base::byte_span_from_ref(capabilities))) {
            service_ok = false;
          }
        });
    const bool handshake = pair.connection->EnsureHandshake();
    service.join();
    EXPECT_TRUE(service_ok);
    EXPECT_EQ(expect_success, handshake);
    return pair;
  }

  void Close(ConnectionPair* pair) {
    if (pair->connection) {
      pair->connection->Abandon();
      pair->connection.reset();
    }
    pair->service_socket.reset();
    task_environment_.RunUntilIdle();
  }

  std::unique_ptr<T1OSVideoDecoder> CreateDecoder(ConnectionPair* pair) {
    return T1OSVideoDecoder::CreateForTesting(
        base::SequencedTaskRunner::GetCurrentDefault(),
        std::make_unique<NullMediaLog>(), FakeFrameResourceConverter::Create(),
        pair->connection);
  }

  template <typename Predicate>
  bool RunUntilReaderTask(Predicate predicate) {
    // Reader-thread completions are posted as immediate owner-sequence tasks.
    // Pump only immediate work so MOCK_TIME cannot jump to an operation
    // deadline while the real reader thread is still scheduling its reply.
    const base::TimeTicks deadline =
        base::subtle::TimeTicksNowIgnoringOverride() +
        TestTimeouts::action_timeout();
    while (base::subtle::TimeTicksNowIgnoringOverride() < deadline) {
      task_environment_.RunUntilIdle();
      if (predicate()) {
        return true;
      }
      base::PlatformThread::Sleep(base::Milliseconds(1));
    }
    task_environment_.RunUntilIdle();
    return predicate();
  }

  void InitializeDecoder(T1OSVideoDecoder* decoder,
                         int service_socket,
                         uint32_t maximum_decode_requests = 1,
                         uint32_t maximum_in_flight_frames = 2) {
    std::optional<DecoderStatus> status;
    decoder->Initialize(
        ValidDecoderConfig(), /*low_delay=*/false, /*cdm_context=*/nullptr,
        base::BindLambdaForTesting([&](DecoderStatus result) {
          status = std::move(result);
        }),
        base::BindLambdaForTesting([](scoped_refptr<VideoFrame>) {}),
        base::BindLambdaForTesting([](WaitingReason) {}));
    t1_media_message_header create = {};
    ASSERT_TRUE(ReceiveHeader(service_socket, &create));
    ASSERT_EQ(T1_MEDIA_CREATE, create.type);
    t1_media_created created = {
        .status = T1_MEDIA_STATUS_OK,
        .maximum_decode_requests = maximum_decode_requests,
        .maximum_in_flight_frames = maximum_in_flight_frames,
        .reserved = 0,
    };
    ASSERT_TRUE(SendWirePacket(
        service_socket, T1_MEDIA_CREATED, kInitialSession, create.request,
        create.generation, base::byte_span_from_ref(created)));
    // The reply is delivered by the connection's real reader thread. A
    // RunLoop under MOCK_TIME can otherwise advance directly to the CREATE
    // deadline before that thread posts its task, turning a successful reply
    // into a deterministic false timeout under load.
    ASSERT_TRUE(RunUntilReaderTask([&]() { return status.has_value(); }));
    ASSERT_TRUE(status.has_value());
    ASSERT_TRUE(status->is_ok());
  }

  base::test::TaskEnvironment task_environment_{
      base::test::TaskEnvironment::TimeSource::MOCK_TIME};
};

TEST_F(T1OSVideoDecoderTest, RejectsHostileCapabilities) {
  std::array<t1_media_capabilities, 3> hostile = {
      ValidCapabilities(), ValidCapabilities(), ValidCapabilities()};
  hostile[0].reserved = 1;
  hostile[1].maximum_decode_requests = T1_MEDIA_MAX_DECODE_REQUESTS + 1;
  hostile[2].features &= ~T1_MEDIA_FEATURE_SEALED_INPUT;
  for (const auto& capabilities : hostile) {
    ConnectionPair pair = Connect(capabilities, /*expect_success=*/false);
    EXPECT_FALSE(pair.connection->is_ready());
    Close(&pair);
  }
}

TEST_F(T1OSVideoDecoderTest, FiltersDepthAndChromaUnsafeCapabilities) {
  t1_media_capabilities capabilities = ValidCapabilities();
  EXPECT_EQ(1u, T1OSConfigsFromCapabilities(capabilities).size());

  capabilities.profiles[0].bit_depths = T1_MEDIA_BIT_DEPTH_10;
  capabilities.profiles[0].output_formats = T1_MEDIA_OUTPUT_P010;
  EXPECT_TRUE(T1OSConfigsFromCapabilities(capabilities).empty());

  capabilities.profiles[0] = {
      .codec = T1_MEDIA_CODEC_VP9,
      .profile = T1_MEDIA_PROFILE_VP9_1,
      .bit_depths = T1_MEDIA_BIT_DEPTH_8,
      .output_formats = T1_MEDIA_OUTPUT_NV12,
      .minimum_width = 16,
      .minimum_height = 16,
      .maximum_width = 4096,
      .maximum_height = 4096,
  };
  EXPECT_TRUE(T1OSConfigsFromCapabilities(capabilities).empty());

  capabilities.profiles[0] = {
      .codec = T1_MEDIA_CODEC_AV1,
      .profile = T1_MEDIA_PROFILE_AV1_MAIN,
      .bit_depths = T1_MEDIA_BIT_DEPTH_8 | T1_MEDIA_BIT_DEPTH_10,
      .output_formats = T1_MEDIA_OUTPUT_NV12 | T1_MEDIA_OUTPUT_P010,
      .minimum_width = 16,
      .minimum_height = 16,
      .maximum_width = 4096,
      .maximum_height = 4096,
  };
  EXPECT_EQ(1u, T1OSConfigsFromCapabilities(capabilities).size());
  capabilities.profiles[0].output_formats = T1_MEDIA_OUTPUT_NV12;
  EXPECT_TRUE(T1OSConfigsFromCapabilities(capabilities).empty());
  capabilities.profiles[0].bit_depths = T1_MEDIA_BIT_DEPTH_8;
  EXPECT_EQ(1u, T1OSConfigsFromCapabilities(capabilities).size());
}

TEST_F(T1OSVideoDecoderTest, AV1CreateDefersBitDepthToDecodedFrame) {
  t1_media_capabilities capabilities = ValidCapabilities();
  capabilities.profiles[0] = {
      .codec = T1_MEDIA_CODEC_AV1,
      .profile = T1_MEDIA_PROFILE_AV1_MAIN,
      .bit_depths = T1_MEDIA_BIT_DEPTH_8 | T1_MEDIA_BIT_DEPTH_10,
      .output_formats = T1_MEDIA_OUTPUT_NV12 | T1_MEDIA_OUTPUT_P010,
      .minimum_width = 16,
      .minimum_height = 16,
      .maximum_width = 4096,
      .maximum_height = 4096,
  };
  ConnectionPair pair = Connect(capabilities);
  std::unique_ptr<T1OSVideoDecoder> decoder = CreateDecoder(&pair);
  ASSERT_TRUE(decoder);

  std::optional<DecoderStatus> status;
  decoder->Initialize(
      ValidAV1DecoderConfig(), /*low_delay=*/false, /*cdm_context=*/nullptr,
      base::BindLambdaForTesting(
          [&](DecoderStatus result) { status = std::move(result); }),
      base::BindLambdaForTesting([](scoped_refptr<VideoFrame>) {}),
      base::BindLambdaForTesting([](WaitingReason) {}));
  t1_media_message_header header = {};
  t1_media_create create = {};
  ASSERT_TRUE(ReceiveCreate(pair.service_socket.get(), &header, &create));
  EXPECT_EQ(T1_MEDIA_CODEC_AV1, create.codec);
  EXPECT_EQ(T1_MEDIA_PROFILE_AV1_MAIN, create.profile);
  EXPECT_EQ(0u, create.bit_depth);
  EXPECT_EQ(T1_MEDIA_CHROMA_420, create.chroma_subsampling);

  t1_media_created rejected = {
      .status = T1_MEDIA_STATUS_UNSUPPORTED_CONFIGURATION,
  };
  ASSERT_TRUE(SendWirePacket(
      pair.service_socket.get(), T1_MEDIA_CREATED, kInitialSession,
      header.request, header.generation, base::byte_span_from_ref(rejected)));
  ASSERT_TRUE(RunUntilReaderTask([&]() { return status.has_value(); }));
  EXPECT_FALSE(status->is_ok());
  decoder.reset();
  Close(&pair);
}

TEST_F(T1OSVideoDecoderTest, EnforcesFrameAndDecodeCredits) {
  ConnectionPair pair = Connect(ValidCapabilities());
  std::unique_ptr<T1OSVideoDecoder> decoder = CreateDecoder(&pair);
  ASSERT_TRUE(decoder);
  EXPECT_TRUE(decoder->FramesHoldExternalResources());
  EXPECT_TRUE(pair.connection->HasFrameCredit());
  EXPECT_TRUE(pair.connection->NoteFrameReady());
  EXPECT_FALSE(pair.connection->HasFrameCredit(/*reserved_decode_frames=*/1));
  EXPECT_TRUE(pair.connection->HasFrameCredit());
  EXPECT_TRUE(pair.connection->NoteFrameReady());
  EXPECT_FALSE(pair.connection->NoteFrameReady());
  EXPECT_FALSE(pair.connection->HasFrameCredit());
  pair.connection->ReleaseFrame(kInitialSession, 1, 99);
  EXPECT_TRUE(pair.connection->NoteFrameReady());

  EXPECT_TRUE(CanIssueT1OSDecode(0, 2));
  EXPECT_TRUE(CanIssueT1OSDecode(1, 2));
  EXPECT_FALSE(CanIssueT1OSDecode(2, 2));
  EXPECT_FALSE(CanIssueT1OSDecode(0, 0));
  Close(&pair);
}

TEST_F(T1OSVideoDecoderTest, CreateTimeoutFailsAndAbandonsConnection) {
  ConnectionPair pair = Connect(ValidCapabilities());
  std::unique_ptr<T1OSVideoDecoder> decoder = CreateDecoder(&pair);
  ASSERT_TRUE(decoder);
  std::optional<DecoderStatus> status;
  decoder->Initialize(
      ValidDecoderConfig(), /*low_delay=*/false, /*cdm_context=*/nullptr,
      base::BindLambdaForTesting(
          [&](DecoderStatus result) { status = std::move(result); }),
      base::BindLambdaForTesting([](scoped_refptr<VideoFrame>) {}),
      base::BindLambdaForTesting([](WaitingReason) {}));
  t1_media_message_header create = {};
  ASSERT_TRUE(ReceiveHeader(pair.service_socket.get(), &create));
  ASSERT_EQ(T1_MEDIA_CREATE, create.type);

  task_environment_.FastForwardBy(base::Seconds(19));
  EXPECT_FALSE(status.has_value());
  EXPECT_TRUE(pair.connection->is_ready());
  task_environment_.FastForwardBy(base::Seconds(2));
  ASSERT_TRUE(status.has_value());
  EXPECT_EQ(DecoderStatus::Codes::kDisconnected, status->code());
  EXPECT_FALSE(pair.connection->is_ready());
  EXPECT_TRUE(WaitForPeerClose(pair.service_socket.get()));
  decoder.reset();
  Close(&pair);
}

TEST_F(T1OSVideoDecoderTest, DecodeTimeoutFailsAndResolvesCallback) {
  ConnectionPair pair = Connect(ValidCapabilities());
  std::unique_ptr<T1OSVideoDecoder> decoder = CreateDecoder(&pair);
  ASSERT_TRUE(decoder);
  InitializeDecoder(decoder.get(), pair.service_socket.get());

  const std::array<uint8_t, 4> bytes = {0, 0, 1, 9};
  std::optional<DecoderStatus> status;
  decoder->Decode(DecoderBuffer::CopyFrom(bytes),
                  base::BindLambdaForTesting([&](DecoderStatus result) {
                    status = std::move(result);
                  }));
  t1_media_message_header decode = {};
  ASSERT_TRUE(ReceiveHeader(pair.service_socket.get(), &decode));
  ASSERT_EQ(T1_MEDIA_DECODE, decode.type);

  task_environment_.FastForwardBy(base::Seconds(29));
  EXPECT_FALSE(status.has_value());
  EXPECT_TRUE(pair.connection->is_ready());
  task_environment_.FastForwardBy(base::Seconds(2));
  ASSERT_TRUE(status.has_value());
  EXPECT_EQ(DecoderStatus::Codes::kDisconnected, status->code());
  EXPECT_FALSE(pair.connection->is_ready());
  EXPECT_TRUE(WaitForPeerClose(pair.service_socket.get()));
  decoder.reset();
  Close(&pair);
}

TEST_F(T1OSVideoDecoderTest, FlushTimeoutFailsAndResolvesCallback) {
  ConnectionPair pair = Connect(ValidCapabilities());
  std::unique_ptr<T1OSVideoDecoder> decoder = CreateDecoder(&pair);
  ASSERT_TRUE(decoder);
  InitializeDecoder(decoder.get(), pair.service_socket.get());

  std::optional<DecoderStatus> status;
  decoder->Decode(DecoderBuffer::CreateEOSBuffer(),
                  base::BindLambdaForTesting([&](DecoderStatus result) {
                    status = std::move(result);
                  }));
  t1_media_message_header flush = {};
  ASSERT_TRUE(ReceiveHeader(pair.service_socket.get(), &flush));
  ASSERT_EQ(T1_MEDIA_FLUSH, flush.type);

  task_environment_.FastForwardBy(base::Seconds(29));
  EXPECT_FALSE(status.has_value());
  EXPECT_TRUE(pair.connection->is_ready());
  task_environment_.FastForwardBy(base::Seconds(2));
  ASSERT_TRUE(status.has_value());
  EXPECT_EQ(DecoderStatus::Codes::kDisconnected, status->code());
  EXPECT_FALSE(pair.connection->is_ready());
  EXPECT_TRUE(WaitForPeerClose(pair.service_socket.get()));
  decoder.reset();
  Close(&pair);
}

TEST_F(T1OSVideoDecoderTest, ResetTimeoutFailsAndResolvesClosure) {
  ConnectionPair pair = Connect(ValidCapabilities());
  std::unique_ptr<T1OSVideoDecoder> decoder = CreateDecoder(&pair);
  ASSERT_TRUE(decoder);
  InitializeDecoder(decoder.get(), pair.service_socket.get());

  const std::array<uint8_t, 4> bytes = {0, 0, 1, 9};
  std::optional<DecoderStatus> decode_status;
  decoder->Decode(DecoderBuffer::CopyFrom(bytes),
                  base::BindLambdaForTesting([&](DecoderStatus result) {
                    decode_status = std::move(result);
                  }));
  t1_media_message_header decode = {};
  ASSERT_TRUE(ReceiveHeader(pair.service_socket.get(), &decode));
  ASSERT_EQ(T1_MEDIA_DECODE, decode.type);

  bool reset_done = false;
  decoder->Reset(base::BindLambdaForTesting([&]() { reset_done = true; }));
  t1_media_message_header reset = {};
  ASSERT_TRUE(ReceiveHeader(pair.service_socket.get(), &reset));
  ASSERT_EQ(T1_MEDIA_RESET, reset.type);

  task_environment_.FastForwardBy(base::Seconds(34));
  EXPECT_FALSE(reset_done);
  EXPECT_FALSE(decode_status.has_value());
  EXPECT_TRUE(pair.connection->is_ready());
  task_environment_.FastForwardBy(base::Seconds(2));
  EXPECT_TRUE(reset_done);
  ASSERT_TRUE(decode_status.has_value());
  EXPECT_EQ(DecoderStatus::Codes::kDisconnected, decode_status->code());
  EXPECT_FALSE(pair.connection->is_ready());
  EXPECT_TRUE(WaitForPeerClose(pair.service_socket.get()));
  decoder.reset();
  Close(&pair);
}

TEST_F(T1OSVideoDecoderTest,
       BackpressurePausesAndEachExitRestartsFullDecodeTimeout) {
  ConnectionPair pair = Connect(ValidCapabilities());
  std::unique_ptr<T1OSVideoDecoder> decoder = CreateDecoder(&pair);
  ASSERT_TRUE(decoder);
  InitializeDecoder(decoder.get(), pair.service_socket.get());

  const std::array<uint8_t, 4> bytes = {0, 0, 1, 9};
  std::optional<DecoderStatus> status;
  decoder->Decode(DecoderBuffer::CopyFrom(bytes),
                  base::BindLambdaForTesting([&](DecoderStatus result) {
                    status = std::move(result);
                  }));
  t1_media_message_header decode = {};
  ASSERT_TRUE(ReceiveHeader(pair.service_socket.get(), &decode));
  ASSERT_EQ(T1_MEDIA_DECODE, decode.type);
  ASSERT_TRUE(pair.connection->NoteFrameReady());
  ASSERT_TRUE(pair.connection->NoteFrameReady());

  t1_media_backpressure enter = {
      .state = T1_MEDIA_BACKPRESSURE_ENTER,
      .in_flight_frames = 2,
  };
  ASSERT_TRUE(SendWirePacket(pair.service_socket.get(), T1_MEDIA_BACKPRESSURE,
                             kInitialSession, decode.request, decode.generation,
                             base::byte_span_from_ref(enter)));
  ASSERT_TRUE(RunUntilReaderTask([&]() {
    return T1OSVideoDecoderTestPeer::IsBackpressured(decoder.get());
  }));
  task_environment_.FastForwardBy(base::Seconds(31));
  EXPECT_FALSE(status.has_value());
  EXPECT_TRUE(pair.connection->is_ready());

  pair.connection->ReleaseFrame(kInitialSession, 1, 1);
  t1_media_message_header release = {};
  ASSERT_TRUE(ReceiveHeader(pair.service_socket.get(), &release));
  ASSERT_EQ(T1_MEDIA_RELEASE, release.type);
  t1_media_backpressure exit = {
      .state = T1_MEDIA_BACKPRESSURE_EXIT,
      .in_flight_frames = 1,
  };
  ASSERT_TRUE(SendWirePacket(pair.service_socket.get(), T1_MEDIA_BACKPRESSURE,
                             kInitialSession, decode.request, decode.generation,
                             base::byte_span_from_ref(exit)));
  ASSERT_TRUE(RunUntilReaderTask([&]() {
    return !T1OSVideoDecoderTestPeer::IsBackpressured(decoder.get());
  }));
  task_environment_.FastForwardBy(base::Seconds(29));
  EXPECT_FALSE(status.has_value());

  ASSERT_TRUE(pair.connection->NoteFrameReady());
  ASSERT_TRUE(SendWirePacket(pair.service_socket.get(), T1_MEDIA_BACKPRESSURE,
                             kInitialSession, decode.request, decode.generation,
                             base::byte_span_from_ref(enter)));
  ASSERT_TRUE(RunUntilReaderTask([&]() {
    return T1OSVideoDecoderTestPeer::IsBackpressured(decoder.get());
  }));
  task_environment_.FastForwardBy(base::Seconds(31));
  EXPECT_FALSE(status.has_value());
  EXPECT_TRUE(pair.connection->is_ready());

  pair.connection->ReleaseFrame(kInitialSession, 1, 2);
  ASSERT_TRUE(ReceiveHeader(pair.service_socket.get(), &release));
  ASSERT_EQ(T1_MEDIA_RELEASE, release.type);
  ASSERT_TRUE(SendWirePacket(pair.service_socket.get(), T1_MEDIA_BACKPRESSURE,
                             kInitialSession, decode.request, decode.generation,
                             base::byte_span_from_ref(exit)));
  ASSERT_TRUE(RunUntilReaderTask([&]() {
    return !T1OSVideoDecoderTestPeer::IsBackpressured(decoder.get());
  }));
  task_environment_.FastForwardBy(base::Seconds(29));
  EXPECT_FALSE(status.has_value());

  t1_media_decode_done done = {
      .status = T1_MEDIA_STATUS_OK,
      .reserved = 0,
  };
  ASSERT_TRUE(SendWirePacket(pair.service_socket.get(), T1_MEDIA_DECODE_DONE,
                             kInitialSession, decode.request, decode.generation,
                             base::byte_span_from_ref(done)));
  ASSERT_TRUE(RunUntilReaderTask([&]() { return status.has_value(); }));
  ASSERT_TRUE(status.has_value());
  EXPECT_TRUE(status->is_ok());
  pair.connection->ReleaseFrame(kInitialSession, 1, 3);
  decoder.reset();
  Close(&pair);
}

TEST_F(T1OSVideoDecoderTest,
       ResetInterruptsBackpressureWithoutExitOrOldTerminal) {
  ConnectionPair pair = Connect(ValidCapabilities());
  std::unique_ptr<T1OSVideoDecoder> decoder = CreateDecoder(&pair);
  ASSERT_TRUE(decoder);
  InitializeDecoder(decoder.get(), pair.service_socket.get());

  const std::array<uint8_t, 4> bytes = {0, 0, 1, 9};
  std::vector<int> completion_order;
  std::optional<DecoderStatus> decode_status;
  decoder->Decode(DecoderBuffer::CopyFrom(bytes),
                  base::BindLambdaForTesting([&](DecoderStatus result) {
                    decode_status = std::move(result);
                    completion_order.push_back(1);
                  }));
  t1_media_message_header decode = {};
  ASSERT_TRUE(ReceiveHeader(pair.service_socket.get(), &decode));
  ASSERT_EQ(T1_MEDIA_DECODE, decode.type);
  ASSERT_TRUE(pair.connection->NoteFrameReady());
  ASSERT_TRUE(pair.connection->NoteFrameReady());
  t1_media_backpressure enter = {
      .state = T1_MEDIA_BACKPRESSURE_ENTER,
      .in_flight_frames = 2,
  };
  ASSERT_TRUE(SendWirePacket(pair.service_socket.get(), T1_MEDIA_BACKPRESSURE,
                             kInitialSession, decode.request, decode.generation,
                             base::byte_span_from_ref(enter)));
  ASSERT_TRUE(RunUntilReaderTask([&]() {
    return T1OSVideoDecoderTestPeer::IsBackpressured(decoder.get());
  }));

  bool reset_done = false;
  decoder->Reset(base::BindLambdaForTesting([&]() {
    completion_order.push_back(2);
    reset_done = true;
  }));
  t1_media_message_header reset = {};
  ASSERT_TRUE(ReceiveHeader(pair.service_socket.get(), &reset));
  ASSERT_EQ(T1_MEDIA_RESET, reset.type);
  EXPECT_FALSE(decode_status.has_value());

  t1_media_result result = {
      .status = T1_MEDIA_STATUS_OK,
      .reserved = 0,
  };
  ASSERT_TRUE(SendWirePacket(pair.service_socket.get(), T1_MEDIA_RESET_DONE,
                             kInitialSession, reset.request, reset.generation,
                             base::byte_span_from_ref(result)));
  ASSERT_TRUE(RunUntilReaderTask([&]() { return reset_done; }));
  ASSERT_TRUE(decode_status.has_value());
  EXPECT_EQ(DecoderStatus::Codes::kAborted, decode_status->code());
  EXPECT_EQ((std::vector<int>{1, 2}), completion_order);
  EXPECT_FALSE(T1OSVideoDecoderTestPeer::IsBackpressured(decoder.get()));
  EXPECT_TRUE(pair.connection->is_ready());

  pair.connection->ReleaseFrame(kInitialSession, decode.generation, 1);
  pair.connection->ReleaseFrame(kInitialSession, decode.generation, 2);
  decoder.reset();
  Close(&pair);
}

TEST_F(T1OSVideoDecoderTest, ResetAbortsQueuedUnsentDecodeBeforeResetClosure) {
  ConnectionPair pair = Connect(ValidCapabilities());
  std::unique_ptr<T1OSVideoDecoder> decoder = CreateDecoder(&pair);
  ASSERT_TRUE(decoder);
  InitializeDecoder(decoder.get(), pair.service_socket.get());
  ASSERT_TRUE(pair.connection->NoteFrameReady());
  ASSERT_TRUE(pair.connection->NoteFrameReady());

  const std::array<uint8_t, 4> bytes = {0, 0, 1, 9};
  std::vector<int> completion_order;
  std::optional<DecoderStatus> decode_status;
  decoder->Decode(DecoderBuffer::CopyFrom(bytes),
                  base::BindLambdaForTesting([&](DecoderStatus result) {
                    decode_status = std::move(result);
                    completion_order.push_back(1);
                  }));
  pollfd no_decode = {
      .fd = pair.service_socket.get(),
      .events = POLLIN,
      .revents = 0,
  };
  EXPECT_EQ(0, HANDLE_EINTR(poll(&no_decode, 1, 0)));

  bool reset_done = false;
  decoder->Reset(base::BindLambdaForTesting([&]() {
    completion_order.push_back(2);
    reset_done = true;
  }));
  t1_media_message_header reset = {};
  ASSERT_TRUE(ReceiveHeader(pair.service_socket.get(), &reset));
  ASSERT_EQ(T1_MEDIA_RESET, reset.type);
  EXPECT_FALSE(decode_status.has_value());

  t1_media_result result = {
      .status = T1_MEDIA_STATUS_OK,
      .reserved = 0,
  };
  ASSERT_TRUE(SendWirePacket(pair.service_socket.get(), T1_MEDIA_RESET_DONE,
                             kInitialSession, reset.request, reset.generation,
                             base::byte_span_from_ref(result)));
  ASSERT_TRUE(RunUntilReaderTask([&]() { return reset_done; }));
  ASSERT_TRUE(decode_status.has_value());
  EXPECT_EQ(DecoderStatus::Codes::kAborted, decode_status->code());
  EXPECT_EQ((std::vector<int>{1, 2}), completion_order);

  pair.connection->ReleaseFrame(kInitialSession, 1, 1);
  pair.connection->ReleaseFrame(kInitialSession, 1, 2);
  decoder.reset();
  Close(&pair);
}

TEST_F(T1OSVideoDecoderTest, RejectsBackpressureInvalidOrderAndCount) {
  const std::array<t1_media_backpressure, 2> hostile = {{
      {
          .state = T1_MEDIA_BACKPRESSURE_EXIT,
          .in_flight_frames = 1,
      },
      {
          .state = T1_MEDIA_BACKPRESSURE_ENTER,
          .in_flight_frames = 1,
      },
  }};
  for (const t1_media_backpressure& backpressure : hostile) {
    ConnectionPair pair = Connect(ValidCapabilities());
    std::unique_ptr<T1OSVideoDecoder> decoder = CreateDecoder(&pair);
    ASSERT_TRUE(decoder);
    InitializeDecoder(decoder.get(), pair.service_socket.get());

    const std::array<uint8_t, 4> bytes = {0, 0, 1, 9};
    std::optional<DecoderStatus> status;
    decoder->Decode(DecoderBuffer::CopyFrom(bytes),
                    base::BindLambdaForTesting([&](DecoderStatus result) {
                      status = std::move(result);
                    }));
    t1_media_message_header decode = {};
    ASSERT_TRUE(ReceiveHeader(pair.service_socket.get(), &decode));
    ASSERT_EQ(T1_MEDIA_DECODE, decode.type);
    ASSERT_TRUE(SendWirePacket(pair.service_socket.get(), T1_MEDIA_BACKPRESSURE,
                               kInitialSession, decode.request,
                               decode.generation,
                               base::byte_span_from_ref(backpressure)));
    ASSERT_TRUE(RunUntilReaderTask([&]() { return status.has_value(); }));
    EXPECT_EQ(DecoderStatus::Codes::kPlatformDecodeFailure, status->code());
    EXPECT_FALSE(pair.connection->is_ready());
    decoder.reset();
    Close(&pair);
  }
}

TEST_F(T1OSVideoDecoderTest, RejectsDuplicateBackpressureEnter) {
  ConnectionPair pair = Connect(ValidCapabilities());
  std::unique_ptr<T1OSVideoDecoder> decoder = CreateDecoder(&pair);
  ASSERT_TRUE(decoder);
  InitializeDecoder(decoder.get(), pair.service_socket.get());

  const std::array<uint8_t, 4> bytes = {0, 0, 1, 9};
  std::optional<DecoderStatus> status;
  decoder->Decode(DecoderBuffer::CopyFrom(bytes),
                  base::BindLambdaForTesting([&](DecoderStatus result) {
                    status = std::move(result);
                  }));
  t1_media_message_header decode = {};
  ASSERT_TRUE(ReceiveHeader(pair.service_socket.get(), &decode));
  ASSERT_EQ(T1_MEDIA_DECODE, decode.type);
  ASSERT_TRUE(pair.connection->NoteFrameReady());
  ASSERT_TRUE(pair.connection->NoteFrameReady());
  t1_media_backpressure enter = {
      .state = T1_MEDIA_BACKPRESSURE_ENTER,
      .in_flight_frames = 2,
  };
  ASSERT_TRUE(SendWirePacket(pair.service_socket.get(), T1_MEDIA_BACKPRESSURE,
                             kInitialSession, decode.request, decode.generation,
                             base::byte_span_from_ref(enter)));
  ASSERT_TRUE(RunUntilReaderTask([&]() {
    return T1OSVideoDecoderTestPeer::IsBackpressured(decoder.get());
  }));
  ASSERT_TRUE(SendWirePacket(pair.service_socket.get(), T1_MEDIA_BACKPRESSURE,
                             kInitialSession, decode.request, decode.generation,
                             base::byte_span_from_ref(enter)));
  ASSERT_TRUE(RunUntilReaderTask([&]() { return status.has_value(); }));
  EXPECT_EQ(DecoderStatus::Codes::kPlatformDecodeFailure, status->code());
  EXPECT_FALSE(pair.connection->is_ready());
  decoder.reset();
  Close(&pair);
}

TEST_F(T1OSVideoDecoderTest, RejectsTerminalReplyWhileBackpressured) {
  ConnectionPair pair = Connect(ValidCapabilities());
  std::unique_ptr<T1OSVideoDecoder> decoder = CreateDecoder(&pair);
  ASSERT_TRUE(decoder);
  InitializeDecoder(decoder.get(), pair.service_socket.get());

  const std::array<uint8_t, 4> bytes = {0, 0, 1, 9};
  std::optional<DecoderStatus> status;
  decoder->Decode(DecoderBuffer::CopyFrom(bytes),
                  base::BindLambdaForTesting([&](DecoderStatus result) {
                    status = std::move(result);
                  }));
  t1_media_message_header decode = {};
  ASSERT_TRUE(ReceiveHeader(pair.service_socket.get(), &decode));
  ASSERT_EQ(T1_MEDIA_DECODE, decode.type);
  ASSERT_TRUE(pair.connection->NoteFrameReady());
  ASSERT_TRUE(pair.connection->NoteFrameReady());
  t1_media_backpressure enter = {
      .state = T1_MEDIA_BACKPRESSURE_ENTER,
      .in_flight_frames = 2,
  };
  ASSERT_TRUE(SendWirePacket(pair.service_socket.get(), T1_MEDIA_BACKPRESSURE,
                             kInitialSession, decode.request, decode.generation,
                             base::byte_span_from_ref(enter)));
  ASSERT_TRUE(RunUntilReaderTask([&]() {
    return T1OSVideoDecoderTestPeer::IsBackpressured(decoder.get());
  }));
  t1_media_decode_done done = {
      .status = T1_MEDIA_STATUS_OK,
      .reserved = 0,
  };
  ASSERT_TRUE(SendWirePacket(pair.service_socket.get(), T1_MEDIA_DECODE_DONE,
                             kInitialSession, decode.request, decode.generation,
                             base::byte_span_from_ref(done)));
  ASSERT_TRUE(RunUntilReaderTask([&]() { return status.has_value(); }));
  EXPECT_EQ(DecoderStatus::Codes::kPlatformDecodeFailure, status->code());
  EXPECT_FALSE(pair.connection->is_ready());
  decoder.reset();
  Close(&pair);
}

TEST_F(T1OSVideoDecoderTest, FrameCreditQueuesAndResumesDecodeWithoutError) {
  t1_media_capabilities capabilities = ValidCapabilities();
  capabilities.maximum_in_flight_frames = T1_MEDIA_MAX_IN_FLIGHT_FRAMES;
  ConnectionPair pair = Connect(capabilities);
  std::unique_ptr<T1OSVideoDecoder> decoder = CreateDecoder(&pair);
  ASSERT_TRUE(decoder);
  InitializeDecoder(decoder.get(), pair.service_socket.get(),
                    /*maximum_decode_requests=*/1,
                    T1_MEDIA_MAX_IN_FLIGHT_FRAMES);

  for (size_t frame = 0; frame < T1_MEDIA_MAX_IN_FLIGHT_FRAMES; ++frame) {
    ASSERT_TRUE(pair.connection->NoteFrameReady());
  }
  EXPECT_FALSE(decoder->CanReadWithoutStalling());
  EXPECT_EQ(1, decoder->GetMaxDecodeRequests());

  const std::array<uint8_t, 4> bytes = {0, 0, 1, 9};
  std::optional<DecoderStatus> status;
  decoder->Decode(DecoderBuffer::CopyFrom(bytes),
                  base::BindLambdaForTesting([&](DecoderStatus result) {
                    status = std::move(result);
                  }));
  pollfd no_decode = {
      .fd = pair.service_socket.get(),
      .events = POLLIN,
      .revents = 0,
  };
  EXPECT_EQ(0, HANDLE_EINTR(poll(&no_decode, 1, 0)));
  EXPECT_FALSE(status.has_value());

  pair.connection->ReleaseFrame(kInitialSession, 1, 1);
  t1_media_message_header release = {};
  ASSERT_TRUE(ReceiveHeader(pair.service_socket.get(), &release));
  ASSERT_EQ(T1_MEDIA_RELEASE, release.type);
  task_environment_.RunUntilIdle();
  t1_media_message_header decode = {};
  ASSERT_TRUE(ReceiveHeader(pair.service_socket.get(), &decode));
  ASSERT_EQ(T1_MEDIA_DECODE, decode.type);
  EXPECT_FALSE(status.has_value());

  t1_media_decode_done done = {
      .status = T1_MEDIA_STATUS_OK,
      .reserved = 0,
  };
  ASSERT_TRUE(SendWirePacket(pair.service_socket.get(), T1_MEDIA_DECODE_DONE,
                             kInitialSession, decode.request, decode.generation,
                             base::byte_span_from_ref(done)));
  ASSERT_TRUE(RunUntilReaderTask([&]() { return status.has_value(); }));
  ASSERT_TRUE(status.has_value());
  EXPECT_TRUE(status->is_ok());

  for (size_t frame = 1; frame < T1_MEDIA_MAX_IN_FLIGHT_FRAMES; ++frame) {
    pair.connection->ReleaseFrame(kInitialSession, 1, frame + 1);
  }
  decoder.reset();
  Close(&pair);
}

TEST_F(T1OSVideoDecoderTest, FlushRunsWithAllClientOwnedFramesAndBackpressure) {
  ConnectionPair pair = Connect(ValidCapabilities());
  std::unique_ptr<T1OSVideoDecoder> decoder = CreateDecoder(&pair);
  ASSERT_TRUE(decoder);
  InitializeDecoder(decoder.get(), pair.service_socket.get());
  ASSERT_TRUE(pair.connection->NoteFrameReady());
  ASSERT_TRUE(pair.connection->NoteFrameReady());

  std::optional<DecoderStatus> status;
  decoder->Decode(DecoderBuffer::CreateEOSBuffer(),
                  base::BindLambdaForTesting([&](DecoderStatus result) {
                    status = std::move(result);
                  }));
  t1_media_message_header flush = {};
  ASSERT_TRUE(ReceiveHeader(pair.service_socket.get(), &flush));
  ASSERT_EQ(T1_MEDIA_FLUSH, flush.type);
  t1_media_backpressure enter = {
      .state = T1_MEDIA_BACKPRESSURE_ENTER,
      .in_flight_frames = 2,
  };
  ASSERT_TRUE(SendWirePacket(pair.service_socket.get(), T1_MEDIA_BACKPRESSURE,
                             kInitialSession, flush.request, flush.generation,
                             base::byte_span_from_ref(enter)));
  ASSERT_TRUE(RunUntilReaderTask([&]() {
    return T1OSVideoDecoderTestPeer::IsBackpressured(decoder.get());
  }));

  pair.connection->ReleaseFrame(kInitialSession, 1, 1);
  t1_media_message_header release = {};
  ASSERT_TRUE(ReceiveHeader(pair.service_socket.get(), &release));
  ASSERT_EQ(T1_MEDIA_RELEASE, release.type);
  t1_media_backpressure exit = {
      .state = T1_MEDIA_BACKPRESSURE_EXIT,
      .in_flight_frames = 1,
  };
  ASSERT_TRUE(SendWirePacket(pair.service_socket.get(), T1_MEDIA_BACKPRESSURE,
                             kInitialSession, flush.request, flush.generation,
                             base::byte_span_from_ref(exit)));
  ASSERT_TRUE(RunUntilReaderTask([&]() {
    return !T1OSVideoDecoderTestPeer::IsBackpressured(decoder.get());
  }));

  t1_media_result result = {
      .status = T1_MEDIA_STATUS_OK,
      .reserved = 0,
  };
  ASSERT_TRUE(SendWirePacket(pair.service_socket.get(), T1_MEDIA_FLUSHED,
                             kInitialSession, flush.request, flush.generation,
                             base::byte_span_from_ref(result)));
  ASSERT_TRUE(RunUntilReaderTask([&]() { return status.has_value(); }));
  ASSERT_TRUE(status.has_value());
  EXPECT_TRUE(status->is_ok());
  pair.connection->ReleaseFrame(kInitialSession, 1, 2);
  decoder.reset();
  Close(&pair);
}

TEST_F(T1OSVideoDecoderTest,
       FlushCompletesAtFullOccupancyWithoutDelayedOutput) {
  ConnectionPair pair = Connect(ValidCapabilities());
  std::unique_ptr<T1OSVideoDecoder> decoder = CreateDecoder(&pair);
  ASSERT_TRUE(decoder);
  InitializeDecoder(decoder.get(), pair.service_socket.get());
  ASSERT_TRUE(pair.connection->NoteFrameReady());
  ASSERT_TRUE(pair.connection->NoteFrameReady());

  std::optional<DecoderStatus> status;
  decoder->Decode(DecoderBuffer::CreateEOSBuffer(),
                  base::BindLambdaForTesting([&](DecoderStatus result) {
                    status = std::move(result);
                  }));
  t1_media_message_header flush = {};
  ASSERT_TRUE(ReceiveHeader(pair.service_socket.get(), &flush));
  ASSERT_EQ(T1_MEDIA_FLUSH, flush.type);
  t1_media_result result = {
      .status = T1_MEDIA_STATUS_OK,
      .reserved = 0,
  };
  ASSERT_TRUE(SendWirePacket(pair.service_socket.get(), T1_MEDIA_FLUSHED,
                             kInitialSession, flush.request, flush.generation,
                             base::byte_span_from_ref(result)));
  ASSERT_TRUE(RunUntilReaderTask([&]() { return status.has_value(); }));
  ASSERT_TRUE(status.has_value());
  EXPECT_TRUE(status->is_ok());

  pair.connection->ReleaseFrame(kInitialSession, 1, 1);
  pair.connection->ReleaseFrame(kInitialSession, 1, 2);
  decoder.reset();
  Close(&pair);
}

TEST_F(T1OSVideoDecoderTest, QueuedUnsentTeardownStillRecyclesConnection) {
  ConnectionPair pair = Connect(ValidCapabilities());
  std::unique_ptr<T1OSVideoDecoder> decoder = CreateDecoder(&pair);
  ASSERT_TRUE(decoder);
  InitializeDecoder(decoder.get(), pair.service_socket.get());
  ASSERT_TRUE(pair.connection->NoteFrameReady());
  ASSERT_TRUE(pair.connection->NoteFrameReady());

  const std::array<uint8_t, 4> bytes = {0, 0, 1, 9};
  std::optional<DecoderStatus> status;
  decoder->Decode(DecoderBuffer::CopyFrom(bytes),
                  base::BindLambdaForTesting([&](DecoderStatus result) {
                    status = std::move(result);
                  }));
  pollfd no_decode = {
      .fd = pair.service_socket.get(),
      .events = POLLIN,
      .revents = 0,
  };
  EXPECT_EQ(0, HANDLE_EINTR(poll(&no_decode, 1, 0)));

  decoder.reset();
  ASSERT_TRUE(status.has_value());
  EXPECT_EQ(DecoderStatus::Codes::kAborted, status->code());
  pair.connection->ReleaseFrame(kInitialSession, 1, 1);
  pair.connection->ReleaseFrame(kInitialSession, 1, 2);
  t1_media_message_header release = {};
  ASSERT_TRUE(ReceiveHeader(pair.service_socket.get(), &release));
  ASSERT_EQ(T1_MEDIA_RELEASE, release.type);
  ASSERT_TRUE(ReceiveHeader(pair.service_socket.get(), &release));
  ASSERT_EQ(T1_MEDIA_RELEASE, release.type);
  t1_media_message_header destroy = {};
  ASSERT_TRUE(ReceiveHeader(pair.service_socket.get(), &destroy));
  EXPECT_EQ(T1_MEDIA_DESTROY, destroy.type);
  Close(&pair);
}

TEST_F(T1OSVideoDecoderTest, QueueFloodDisconnectsAndClosesPassedFds) {
  ConnectionPair pair = Connect(ValidCapabilities());
  size_t delivered = 0;
  bool disconnected = false;
  ASSERT_TRUE(pair.connection->SetClient(
      base::BindLambdaForTesting([&](T1OSDecoderPacket) { ++delivered; }),
      base::BindLambdaForTesting([&]() { disconnected = true; }),
      base::BindLambdaForTesting([]() {})));

  std::array<int, 2> passed = {-1, -1};
  ASSERT_EQ(socketpair(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0, passed.data()),
            0);
  base::ScopedFD probe(passed[1]);
  std::atomic<size_t> sent = 0;
  std::atomic<bool> media_closed = false;
  std::thread service([socket = pair.service_socket.get(),
                       pass = base::ScopedFD(passed[0]), &sent,
                       &media_closed]() {
    t1_media_created created = {};
    const int descriptor = pass.get();
    for (uint64_t request = 1; request <= 128; ++request) {
      if (!SendWirePacket(socket, T1_MEDIA_CREATED, kInitialSession, request, 1,
                          base::byte_span_from_ref(created),
                          base::span_from_ref(descriptor))) {
        break;
      }
      ++sent;
    }
    media_closed = WaitForPeerClose(socket);
  });
  service.join();

  EXPECT_GT(sent.load(),
            static_cast<size_t>(T1_MEDIA_MAX_DECODE_REQUESTS +
                                T1_MEDIA_MAX_IN_FLIGHT_FRAMES + 8));
  EXPECT_TRUE(media_closed);
  EXPECT_EQ(0u, delivered);
  task_environment_.RunUntilIdle();
  EXPECT_TRUE(disconnected);
  EXPECT_LE(delivered, static_cast<size_t>(T1_MEDIA_MAX_DECODE_REQUESTS +
                                           T1_MEDIA_MAX_IN_FLIGHT_FRAMES + 8));
  EXPECT_TRUE(WaitForPeerClose(probe.get()));
  Close(&pair);
}

TEST_F(T1OSVideoDecoderTest, PacketCallbackCanTearDownReentrantly) {
  ConnectionPair pair = Connect(ValidCapabilities());
  bool called = false;
  ASSERT_TRUE(pair.connection->SetClient(
      base::BindLambdaForTesting([&](T1OSDecoderPacket) {
        called = true;
        pair.connection->ClearClient();
        pair.connection->Abandon();
        pair.connection.reset();
      }),
      base::BindLambdaForTesting([]() {}),
      base::BindLambdaForTesting([]() {})));

  std::atomic<bool> media_closed = false;
  std::thread service([socket = pair.service_socket.get(), &media_closed]() {
    t1_media_created created = {};
    SendWirePacket(socket, T1_MEDIA_CREATED, kInitialSession, 10, 1,
                   base::byte_span_from_ref(created));
    media_closed = WaitForPeerClose(socket);
  });
  ASSERT_TRUE(RunUntilReaderTask([&]() { return called; }));
  service.join();
  EXPECT_TRUE(called);
  EXPECT_TRUE(media_closed);
  pair.service_socket.reset();
  task_environment_.RunUntilIdle();
}

TEST_F(T1OSVideoDecoderTest, NonblockingSendFailsClosedUnderBackpressure) {
  std::array<int, 2> sockets = {-1, -1};
  ASSERT_EQ(
      socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0, sockets.data()), 0);
  int send_buffer = 8192;
  ASSERT_EQ(setsockopt(sockets[0], SOL_SOCKET, SO_SNDBUF, &send_buffer,
                       sizeof(send_buffer)),
            0);
  ConnectionPair pair = {
      .connection = base::MakeRefCounted<T1OSDecoderConnection>(
          base::ScopedFD(sockets[0]),
          base::SequencedTaskRunner::GetCurrentDefault()),
      .service_socket = base::ScopedFD(sockets[1]),
  };
  t1_media_capabilities capabilities = ValidCapabilities();
  std::thread service([socket = pair.service_socket.get(), &capabilities]() {
    t1_media_message_header hello = {};
    if (ReceiveHeader(socket, &hello)) {
      SendWirePacket(socket, T1_MEDIA_CAPABILITIES, kInitialSession,
                     hello.request, 0, base::byte_span_from_ref(capabilities));
    }
  });
  ASSERT_TRUE(pair.connection->EnsureHandshake());
  service.join();

  std::vector<uint8_t> payload(4096, 0x5a);
  const base::TimeTicks started = base::TimeTicks::Now();
  std::optional<uint64_t> request;
  for (size_t attempt = 0; attempt < 4096; ++attempt) {
    request =
        pair.connection->Send(T1_MEDIA_CREATE, kInitialSession, 1, 0, payload);
    if (!request) {
      break;
    }
  }
  EXPECT_FALSE(request);
  EXPECT_LT(base::TimeTicks::Now() - started, base::Seconds(1));
  EXPECT_FALSE(pair.connection->is_ready());
  Close(&pair);
}

TEST_F(T1OSVideoDecoderTest, DestroyTimeoutFailsClosed) {
  ConnectionPair pair = Connect(ValidCapabilities());
  ASSERT_TRUE(pair.connection->NoteFrameReady());
  bool recycled = false;
  pair.connection->BeginRecycle(
      kInitialSession, 1,
      base::BindLambdaForTesting(
          [&](scoped_refptr<T1OSDecoderConnection>) { recycled = true; }));
  pair.connection->ReleaseFrame(kInitialSession, 1, 1);
  t1_media_message_header release = {};
  ASSERT_TRUE(ReceiveHeader(pair.service_socket.get(), &release));
  ASSERT_EQ(T1_MEDIA_RELEASE, release.type);
  t1_media_message_header destroy = {};
  ASSERT_TRUE(ReceiveHeader(pair.service_socket.get(), &destroy));
  ASSERT_EQ(T1_MEDIA_DESTROY, destroy.type);

  task_environment_.FastForwardBy(base::Seconds(24));
  EXPECT_FALSE(recycled);
  pollfd still_open = {
      .fd = pair.service_socket.get(),
      .events = POLLIN | POLLHUP | POLLERR,
      .revents = 0,
  };
  EXPECT_EQ(0, HANDLE_EINTR(poll(&still_open, 1, 0)));
  task_environment_.FastForwardBy(base::Seconds(2));
  EXPECT_FALSE(recycled);
  EXPECT_FALSE(pair.connection->is_ready());
  EXPECT_TRUE(WaitForPeerClose(pair.service_socket.get()));
  Close(&pair);
}

TEST_F(T1OSVideoDecoderTest, ConcurrentRecycleEligibilitySendsOneDestroy) {
  ConnectionPair pair = Connect(ValidCapabilities());
  ASSERT_TRUE(pair.connection->NoteFrameReady());
  pair.connection->BeginRecycle(
      kInitialSession, 1,
      base::BindLambdaForTesting([](scoped_refptr<T1OSDecoderConnection>) {}));

  // Make the same state ReleaseFrame() and DeliverPacket() race to observe,
  // then start both callers together. The send/state lock transaction must
  // record one request before the second caller can become eligible.
  T1OSDecoderConnectionTestPeer::MakeRecycleEligibleWithoutStartingDestroy(
      pair.connection.get());
  base::WaitableEvent start(base::WaitableEvent::ResetPolicy::MANUAL,
                            base::WaitableEvent::InitialState::NOT_SIGNALED);
  std::thread release_caller([&]() {
    start.Wait();
    T1OSDecoderConnectionTestPeer::MaybeStartDestroy(pair.connection.get());
  });
  std::thread delivery_caller([&]() {
    start.Wait();
    T1OSDecoderConnectionTestPeer::MaybeStartDestroy(pair.connection.get());
  });
  start.Signal();
  release_caller.join();
  delivery_caller.join();

  t1_media_message_header destroy = {};
  ASSERT_TRUE(ReceiveHeader(pair.service_socket.get(), &destroy));
  ASSERT_EQ(T1_MEDIA_DESTROY, destroy.type);
  pollfd no_duplicate = {
      .fd = pair.service_socket.get(),
      .events = POLLIN,
      .revents = 0,
  };
  EXPECT_EQ(0, HANDLE_EINTR(poll(&no_duplicate, 1, 0)));
  Close(&pair);
}

TEST_F(T1OSVideoDecoderTest, RehelloCapabilityChangeFailsClosed) {
  const t1_media_capabilities capabilities = ValidCapabilities();
  ConnectionPair pair = Connect(capabilities);
  ASSERT_TRUE(pair.connection->SetClient(
      base::BindLambdaForTesting([](T1OSDecoderPacket) {}),
      base::BindLambdaForTesting([]() {}),
      base::BindLambdaForTesting([]() {})));
  std::atomic<bool> service_ok = true;
  std::atomic<bool> media_closed = false;
  std::thread service([socket = pair.service_socket.get(), &capabilities,
                       &service_ok, &media_closed]() {
    t1_media_message_header destroy = {};
    t1_media_result result = {.status = T1_MEDIA_STATUS_OK, .reserved = 0};
    if (!ReceiveHeader(socket, &destroy) || destroy.type != T1_MEDIA_DESTROY ||
        !SendWirePacket(socket, T1_MEDIA_DESTROY, destroy.session,
                        destroy.request, destroy.generation,
                        base::byte_span_from_ref(result))) {
      service_ok = false;
      return;
    }
    t1_media_message_header hello = {};
    if (!ReceiveHeader(socket, &hello) || hello.type != T1_MEDIA_HELLO) {
      service_ok = false;
      return;
    }
    t1_media_capabilities changed = capabilities;
    changed.maximum_in_flight_frames = 1;
    if (!SendWirePacket(socket, T1_MEDIA_CAPABILITIES, kInitialSession + 1,
                        hello.request, 0, base::byte_span_from_ref(changed))) {
      service_ok = false;
      return;
    }
    media_closed = WaitForPeerClose(socket);
  });
  bool recycled = false;
  pair.connection->BeginRecycle(
      kInitialSession, 1,
      base::BindLambdaForTesting(
          [&](scoped_refptr<T1OSDecoderConnection>) { recycled = true; }));
  service.join();
  task_environment_.RunUntilIdle();
  EXPECT_TRUE(service_ok);
  EXPECT_TRUE(media_closed);
  EXPECT_FALSE(recycled);
  EXPECT_FALSE(pair.connection->is_ready());
  Close(&pair);
}

TEST_F(T1OSVideoDecoderTest, RehelloTimeoutExceedsNativeHelloWatchdog) {
  ConnectionPair pair = Connect(ValidCapabilities());
  ASSERT_TRUE(pair.connection->SetClient(
      base::BindLambdaForTesting([](T1OSDecoderPacket) {}),
      base::BindLambdaForTesting([]() {}),
      base::BindLambdaForTesting([]() {})));
  bool recycled = false;
  pair.connection->BeginRecycle(
      kInitialSession, 1,
      base::BindLambdaForTesting(
          [&](scoped_refptr<T1OSDecoderConnection>) { recycled = true; }));
  t1_media_message_header destroy = {};
  ASSERT_TRUE(ReceiveHeader(pair.service_socket.get(), &destroy));
  ASSERT_EQ(T1_MEDIA_DESTROY, destroy.type);
  t1_media_result result = {
      .status = T1_MEDIA_STATUS_OK,
      .reserved = 0,
  };
  ASSERT_TRUE(SendWirePacket(
      pair.service_socket.get(), T1_MEDIA_DESTROY, destroy.session,
      destroy.request, destroy.generation, base::byte_span_from_ref(result)));
  t1_media_message_header hello = {};
  ASSERT_TRUE(ReceiveHeader(pair.service_socket.get(), &hello));
  ASSERT_EQ(T1_MEDIA_HELLO, hello.type);

  task_environment_.FastForwardBy(base::Seconds(7));
  EXPECT_FALSE(recycled);
  pollfd still_open = {
      .fd = pair.service_socket.get(),
      .events = POLLIN | POLLHUP | POLLERR,
      .revents = 0,
  };
  EXPECT_EQ(0, HANDLE_EINTR(poll(&still_open, 1, 0)));
  task_environment_.FastForwardBy(base::Seconds(2));
  EXPECT_FALSE(recycled);
  EXPECT_FALSE(pair.connection->is_ready());
  EXPECT_TRUE(WaitForPeerClose(pair.service_socket.get()));
  Close(&pair);
}

TEST_F(T1OSVideoDecoderTest, ValidatesFrameTopologyExtentAndObjectType) {
  const t1_media_frame valid = ValidNV12Frame();
  EXPECT_TRUE(ValidateT1OSFrameLayout(valid, 1));
  EXPECT_TRUE(ValidateT1OSFrameLayout(
      ValidSeparateNV12Frame(T1_MEDIA_DRM_FORMAT_RG88), 2));
  EXPECT_TRUE(ValidateT1OSFrameLayout(
      ValidSeparateNV12Frame(T1_MEDIA_DRM_FORMAT_GR88), 2));
  t1_media_frame synthetic_common_object =
      ValidSeparateNV12Frame(T1_MEDIA_DRM_FORMAT_RG88);
  synthetic_common_object.object_count = 1;
  synthetic_common_object.objects[0].size = 6144;
  synthetic_common_object.layers[1].planes[0].object_index = 0;
  synthetic_common_object.layers[1].planes[0].offset = 4096;
  EXPECT_FALSE(ValidateT1OSFrameLayout(synthetic_common_object, 1));
  t1_media_frame composed_dmabuf = valid;
  composed_dmabuf.flags &= ~T1_MEDIA_FRAME_LINEAR_MEMORY;
  EXPECT_FALSE(ValidateT1OSFrameLayout(composed_dmabuf, 1));
  t1_media_frame linear = valid;
  EXPECT_TRUE(ValidateT1OSFrameLayout(linear, 1));
  linear.object_count = 2;
  EXPECT_FALSE(ValidateT1OSFrameLayout(linear, 2));

  t1_media_frame hostile = valid;
  hostile.layers[0].drm_fourcc = T1_MEDIA_DRM_FORMAT_P010;
  EXPECT_FALSE(ValidateT1OSFrameLayout(hostile, 1));
  hostile = valid;
  hostile.layers[0].planes[1].offset = 2048;
  EXPECT_FALSE(ValidateT1OSFrameLayout(hostile, 1));
  hostile = valid;
  hostile.objects[0].size = 5000;
  EXPECT_FALSE(ValidateT1OSFrameLayout(hostile, 1));
  hostile = valid;
  hostile.object_count = 2;
  hostile.objects[1] = {.size = 4096, .modifier = 0};
  EXPECT_FALSE(ValidateT1OSFrameLayout(hostile, 2));
  hostile = valid;
  hostile.visible_x = 63;
  hostile.visible_width = 2;
  EXPECT_FALSE(ValidateT1OSFrameLayout(hostile, 1));
  hostile = valid;
  hostile.layers[0].planes[0].reserved = 1;
  EXPECT_FALSE(ValidateT1OSFrameLayout(hostile, 1));
  EXPECT_FALSE(ValidateT1OSFrameLayout(valid, 2));

  base::ScopedTempDir temporary;
  ASSERT_TRUE(temporary.CreateUniqueTempDir());
  base::ScopedFD ordinary_file(HANDLE_EINTR(
      open(temporary.GetPath().AppendASCII("not-a-dmabuf").value().c_str(),
           O_RDWR | O_CREAT | O_CLOEXEC, 0600)));
  ASSERT_TRUE(ordinary_file.is_valid());
  ASSERT_EQ(HANDLE_EINTR(ftruncate(ordinary_file.get(), 8192)), 0);
  EXPECT_FALSE(IsValidT1OSDmaBufObject(ordinary_file.get(), 6144));

  base::ScopedFD linear_memory(
      memfd_create("t1os-linear-frame-test",
                   MFD_CLOEXEC | MFD_ALLOW_SEALING));
  ASSERT_TRUE(linear_memory.is_valid());
  ASSERT_EQ(HANDLE_EINTR(ftruncate(linear_memory.get(), 6144)), 0);
  EXPECT_FALSE(IsValidT1OSLinearMemoryObject(linear_memory.get(), 6144));
  ASSERT_EQ(fcntl(linear_memory.get(), F_ADD_SEALS,
                  F_SEAL_SEAL | F_SEAL_SHRINK |
                      F_SEAL_GROW | F_SEAL_WRITE),
            0);
  EXPECT_TRUE(IsValidT1OSLinearMemoryObject(linear_memory.get(), 6144));
  EXPECT_FALSE(IsValidT1OSLinearMemoryObject(linear_memory.get(), 4096));
}

TEST_F(T1OSVideoDecoderTest, PreservesProducerChromaOrderInNativePixmap) {
  const gfx::Size coded_size(64, 64);
  std::vector<ColorPlaneLayout> planes;
  planes.emplace_back(64, 0, 4096);
  planes.emplace_back(64, 4096, 2048);
  auto layout = VideoFrameLayout::CreateWithPlanes(
      PIXEL_FORMAT_NV12, coded_size, std::move(planes),
      VideoFrameLayout::kBufferAddressAlignment, /*modifier=*/0);
  ASSERT_TRUE(layout.has_value());

  base::ScopedFD object(memfd_create("t1os-plane-fourcc-test", MFD_CLOEXEC));
  ASSERT_TRUE(object.is_valid());
  ASSERT_EQ(0, HANDLE_EINTR(ftruncate(object.get(), 6144)));
  std::vector<base::ScopedFD> descriptors;
  descriptors.emplace_back(HANDLE_EINTR(dup(object.get())));
  descriptors.emplace_back(HANDLE_EINTR(dup(object.get())));
  ASSERT_TRUE(descriptors[0].is_valid());
  ASSERT_TRUE(descriptors[1].is_valid());

  auto resource = NativePixmapFrameResource::CreateForT1OS(
      *layout, gfx::Rect(coded_size), coded_size, std::move(descriptors),
      std::vector<uint64_t>{0, 0}, base::TimeDelta(),
      /*chroma_is_drm_rg=*/true);
  ASSERT_TRUE(resource);
  EXPECT_FALSE(resource->metadata().is_webgpu_compatible);
  gfx::GpuMemoryBufferHandle handle =
      resource->CreateGpuMemoryBufferHandle();
  ASSERT_EQ(gfx::NATIVE_PIXMAP, handle.type);
  EXPECT_TRUE(handle.native_pixmap_handle().t1os_chroma_is_drm_rg);
  EXPECT_FALSE(
      handle.native_pixmap_handle().supports_zero_copy_webgpu_import);
}

TEST_F(T1OSVideoDecoderTest, DropsStaleSourceAndEpochIdentities) {
  ConnectionPair current = Connect(ValidCapabilities());
  ConnectionPair stale = Connect(ValidCapabilities());
  EXPECT_TRUE(IsCurrentT1OSDecoderClient(current.connection.get(),
                                         current.connection.get(), 7, 7));
  EXPECT_FALSE(IsCurrentT1OSDecoderClient(stale.connection.get(),
                                          current.connection.get(), 7, 7));
  EXPECT_FALSE(IsCurrentT1OSDecoderClient(current.connection.get(),
                                          current.connection.get(), 6, 7));
  EXPECT_FALSE(
      IsCurrentT1OSDecoderClient(nullptr, current.connection.get(), 7, 7));
  Close(&stale);
  Close(&current);
}

TEST(T1OSVideoDecoderStaticTest, ProfileMappingsAreExplicitAndSymmetric) {
  constexpr std::array<VideoCodecProfile, 11> kProfiles = {
      H264PROFILE_BASELINE, H264PROFILE_MAIN,        H264PROFILE_HIGH,
      VP8PROFILE_ANY,       VP9PROFILE_PROFILE0,     VP9PROFILE_PROFILE1,
      VP9PROFILE_PROFILE2,  VP9PROFILE_PROFILE3,     HEVCPROFILE_MAIN,
      HEVCPROFILE_MAIN10,   AV1PROFILE_PROFILE_MAIN,
  };
  for (VideoCodecProfile profile : kProfiles) {
    const uint32_t wire = ChromiumProfileToT1OSProfile(profile);
    EXPECT_NE(T1_MEDIA_PROFILE_UNKNOWN, wire);
    ASSERT_TRUE(T1OSProfileToChromiumProfile(wire).has_value());
    EXPECT_EQ(profile, *T1OSProfileToChromiumProfile(wire));
  }
}

TEST(T1OSVideoDecoderStaticTest, ImportLayerFormatsAreUnique) {
  const std::array<uint32_t, 6> formats = {
      T1_MEDIA_DRM_FORMAT_R8,     T1_MEDIA_DRM_FORMAT_RG88,
      T1_MEDIA_DRM_FORMAT_GR88,   T1_MEDIA_DRM_FORMAT_R16,
      T1_MEDIA_DRM_FORMAT_RG1616, T1_MEDIA_DRM_FORMAT_GR1616,
  };
  EXPECT_EQ(formats.size(),
            std::set<uint32_t>(formats.begin(), formats.end()).size());
  EXPECT_LE(formats.size(), static_cast<size_t>(T1_MEDIA_MAX_IMPORT_FOURCC));
}

TEST(T1OSVideoDecoderStaticTest, WireHeaderRemainsT1MDVersion1) {
  EXPECT_EQ(UINT32_C(0x444d3154), T1_MEDIA_PROTOCOL_MAGIC);
  EXPECT_EQ(UINT16_C(1), T1_MEDIA_PROTOCOL_VERSION);
  EXPECT_EQ(40u, sizeof(t1_media_message_header));
}

}  // namespace
}  // namespace media
