// Copyright 2026 The One OS Authors
// Use of this source code is governed by a BSD-style license.

#include "media/gpu/t1os/t1os_decoder_connection.h"

#include <errno.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

#include <algorithm>
#include <array>
#include <cstring>
#include <limits>
#include <string>
#include <utility>

#include "base/compiler_specific.h"
#include "base/environment.h"
#include "base/feature_list.h"
#include "base/file_descriptor_store.h"
#include "base/functional/bind.h"
#include "base/logging.h"
#include "base/no_destructor.h"
#include "base/numerics/safe_conversions.h"
#include "base/posix/eintr_wrapper.h"
#include "base/strings/stringprintf.h"
#include "base/task/sequenced_task_runner.h"
#include "base/task/task_traits.h"
#include "base/task/thread_pool.h"
#include "base/threading/scoped_blocking_call.h"
#include "base/threading/thread.h"
#include "base/time/time.h"
#include "media/base/t1os_media_switches.h"

namespace media {
namespace {

// The native supervisor owns the authoritative STARTING (15 second), HELLO
// (5 second), and DESTROY (10 second) watchdogs. The initial descriptor may be
// exposed before STARTING completes, so Chromium allows both native windows.
// DESTROY can sit behind a preceding RELEASE (6 seconds), so its fallback also
// covers both native windows.
constexpr int kInitialHandshakeTimeoutMilliseconds = 30000;
constexpr base::TimeDelta kDestroyTimeout = base::Seconds(25);
constexpr base::TimeDelta kRehelloTimeout = base::Seconds(8);
constexpr size_t kMaximumQueuedPackets =
    T1_MEDIA_MAX_DECODE_REQUESTS + T1_MEDIA_MAX_IN_FLIGHT_FRAMES + 8;
constexpr size_t kMaximumQueuedDescriptors =
    T1_MEDIA_MAX_IN_FLIGHT_FRAMES * T1_MEDIA_MAX_FRAME_OBJECTS;
constexpr uint32_t kCommonRequiredFeatures =
    T1_MEDIA_FEATURE_SEALED_INPUT | T1_MEDIA_FEATURE_RESET |
    T1_MEDIA_FEATURE_BACKPRESSURE;

scoped_refptr<base::SequencedTaskRunner> ConnectionDeletionTaskRunner() {
  // RefCountedDeleteOnSequence must not delete a connection on Chromium's
  // media sequence: its destructor joins the dedicated blocking socket
  // reader, and that sequence deliberately disallows blocking. A MayBlock
  // deletion sequence with base synchronization permission makes the
  // unavoidable bounded Thread::Stop() join legal without weakening the
  // media sequence's thread restrictions. Keep this runner per connection:
  // a process-static pooled runner outlives successive TaskEnvironments in
  // Chromium's test launcher and becomes stale.
  return base::ThreadPool::CreateSequencedTaskRunner(
      {base::MayBlock(), base::WithBaseSyncPrimitives(),
       base::TaskShutdownBehavior::BLOCK_SHUTDOWN});
}

uint32_t RequiredFeaturesForProcess() {
  auto environment = base::Environment::Create();
  const auto output_mode =
      environment->GetVar(kT1OSMediaDecodeOutputEnvironment);
  if (!output_mode || *output_mode == kT1OSMediaDecodeOutputLinearMemory) {
    return kCommonRequiredFeatures | T1_MEDIA_FEATURE_LINEAR_MEMORY_OUTPUT;
  }
  if (*output_mode == kT1OSMediaDecodeOutputDmaBuf) {
    return kCommonRequiredFeatures | T1_MEDIA_FEATURE_DMABUF;
  }
  LOG(ERROR) << "T1MD rejected unknown "
             << kT1OSMediaDecodeOutputEnvironment << " mode";
  return 0;
}

bool HasRequiredCapabilities(const t1_media_capabilities& capabilities) {
  const uint32_t required_features = RequiredFeaturesForProcess();
  return required_features != 0 &&
         (capabilities.features & required_features) == required_features &&
         capabilities.maximum_sessions >= kT1OSMediaDecodeDescriptorPoolSize &&
         capabilities.profile_count <= T1_MEDIA_MAX_PROFILES &&
         capabilities.maximum_decode_requests > 0 &&
         capabilities.maximum_decode_requests <= T1_MEDIA_MAX_DECODE_REQUESTS &&
         capabilities.maximum_in_flight_frames > 0 &&
         capabilities.maximum_in_flight_frames <=
             T1_MEDIA_MAX_IN_FLIGHT_FRAMES &&
         capabilities.maximum_encoded_bytes > 0 &&
         capabilities.maximum_encoded_bytes <= T1_MEDIA_MAX_ENCODED_BYTES &&
         capabilities.maximum_extradata_bytes <= T1_MEDIA_MAX_EXTRADATA_BYTES &&
         capabilities.reserved == 0;
}

bool ProfileMatchesCodec(uint32_t profile, uint32_t codec) {
  switch (profile) {
    case T1_MEDIA_PROFILE_H264_BASELINE:
    case T1_MEDIA_PROFILE_H264_MAIN:
    case T1_MEDIA_PROFILE_H264_HIGH:
      return codec == T1_MEDIA_CODEC_H264;
    case T1_MEDIA_PROFILE_VP8_ANY:
      return codec == T1_MEDIA_CODEC_VP8;
    case T1_MEDIA_PROFILE_VP9_0:
    case T1_MEDIA_PROFILE_VP9_1:
    case T1_MEDIA_PROFILE_VP9_2:
    case T1_MEDIA_PROFILE_VP9_3:
      return codec == T1_MEDIA_CODEC_VP9;
    case T1_MEDIA_PROFILE_HEVC_MAIN:
    case T1_MEDIA_PROFILE_HEVC_MAIN10:
      return codec == T1_MEDIA_CODEC_HEVC;
    case T1_MEDIA_PROFILE_AV1_MAIN:
      return codec == T1_MEDIA_CODEC_AV1;
    default:
      return false;
  }
}

uint32_t ExpectedBitDepthsForProfile(uint32_t profile) {
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
      // AV1 Main uses one Chromium profile for both 8- and 10-bit streams.
      return T1_MEDIA_BIT_DEPTH_8 | T1_MEDIA_BIT_DEPTH_10;
    default:
      // T1MD transports 4:2:0 NV12/P010 only.  VP9 profiles 1 and 3 permit
      // chroma layouts that this bridge cannot describe and must not leak into
      // Chromium's supported-config list.
      return 0;
  }
}

bool ProfileHasUsableOutput(const t1_media_capability_profile& profile) {
  const uint32_t expected_bit_depths =
      ExpectedBitDepthsForProfile(profile.profile);
  if (expected_bit_depths == 0 || profile.bit_depths == 0 ||
      (profile.bit_depths & ~expected_bit_depths) != 0) {
    return false;
  }
  if ((profile.bit_depths & T1_MEDIA_BIT_DEPTH_8) != 0 &&
      (profile.output_formats & T1_MEDIA_OUTPUT_NV12) == 0) {
    return false;
  }
  if ((profile.bit_depths & T1_MEDIA_BIT_DEPTH_10) != 0 &&
      (profile.output_formats & T1_MEDIA_OUTPUT_P010) == 0) {
    return false;
  }
  return true;
}

}  // namespace

T1OSDecoderConnection::T1OSDecoderConnection(
    base::ScopedFD socket,
    scoped_refptr<base::SequencedTaskRunner> owner_task_runner)
    : base::RefCountedDeleteOnSequence<T1OSDecoderConnection>(
          ConnectionDeletionTaskRunner()),
      socket_(std::move(socket)),
      owner_task_runner_(std::move(owner_task_runner)) {
  CHECK(socket_.is_valid());
  CHECK(owner_task_runner_);
}

T1OSDecoderConnection::~T1OSDecoderConnection() {
  {
    base::AutoLock socket_lock(socket_lifecycle_lock_);
    if (socket_.is_valid()) {
      shutdown(socket_.get(), SHUT_RDWR);
    }
  }
  if (reader_thread_.IsRunning()) {
    // ConnectionDeletionTaskRunner has MayBlock permission. Mark the exact
    // join so ThreadPool can compensate while shutdown() wakes the reader.
    base::ScopedBlockingCall allow_thread_join(FROM_HERE,
                                                base::BlockingType::MAY_BLOCK);
    reader_thread_.Stop();
  }
  base::AutoLock send_lock(send_lock_);
  base::AutoLock socket_lock(socket_lifecycle_lock_);
  socket_.reset();
}

bool T1OSDecoderConnection::EnsureHandshake() {
  {
    base::AutoLock lock(state_lock_);
    if (ready_) {
      return true;
    }
    if (disconnected_) {
      return false;
    }
  }
  if (!SendHello()) {
    return false;
  }

  pollfd event = {.fd = socket_.get(), .events = POLLIN, .revents = 0};
  const int result =
      HANDLE_EINTR(poll(&event, 1, kInitialHandshakeTimeoutMilliseconds));
  if (result <= 0 || !(event.revents & POLLIN)) {
    if (result == 0) {
      LOG(ERROR) << "T1MD HELLO timed out";
    } else {
      PLOG(ERROR) << "T1MD HELLO poll failed";
    }
    NotifyDisconnect();
    return false;
  }

  std::optional<T1OSDecoderPacket> packet = ReceivePacketBlocking();
  t1_media_capabilities capabilities = {};
  uint64_t session = 0;
  if (!packet ||
      !ValidateCapabilitiesPacket(*packet, &capabilities, &session)) {
    LOG(ERROR) << "T1MD did not return a valid CAPABILITIES packet";
    NotifyDisconnect();
    return false;
  }

  {
    base::AutoLock lock(state_lock_);
    capabilities_ = capabilities;
    session_ = session;
    hello_request_ = 0;
    ready_ = true;
  }
  return true;
}

bool T1OSDecoderConnection::is_ready() const {
  base::AutoLock lock(state_lock_);
  return ready_ && !disconnected_;
}

uint64_t T1OSDecoderConnection::session() const {
  base::AutoLock lock(state_lock_);
  return ready_ && !disconnected_ ? session_ : 0;
}

t1_media_capabilities T1OSDecoderConnection::capabilities() const {
  base::AutoLock lock(state_lock_);
  return ready_ && !disconnected_ ? capabilities_ : t1_media_capabilities{};
}

bool T1OSDecoderConnection::SetClient(PacketCB packet_cb,
                                      DisconnectCB disconnect_cb,
                                      FrameCreditCB frame_credit_cb) {
  CHECK(owner_task_runner_->RunsTasksInCurrentSequence());
  {
    base::AutoLock lock(state_lock_);
    if (!ready_ || disconnected_ || !packet_cb_.is_null() ||
        !recycle_cb_.is_null()) {
      return false;
    }
    packet_cb_ = std::move(packet_cb);
    disconnect_cb_ = std::move(disconnect_cb);
    frame_credit_cb_ = std::move(frame_credit_cb);
  }
  if (!StartReader()) {
    NotifyDisconnect();
    return false;
  }
  return true;
}

void T1OSDecoderConnection::ClearClient() {
  base::AutoLock lock(state_lock_);
  packet_cb_.Reset();
  disconnect_cb_.Reset();
  frame_credit_cb_.Reset();
}

void T1OSDecoderConnection::Abandon() {
  CHECK(owner_task_runner_->RunsTasksInCurrentSequence());
  ClearClient();
  NotifyDisconnect();
}

std::optional<uint64_t> T1OSDecoderConnection::Send(
    uint16_t type,
    uint64_t session,
    uint64_t generation,
    uint32_t flags,
    base::span<const uint8_t> payload,
    base::span<const int> descriptors) {
  base::AutoLock send_lock(send_lock_);
  return SendPacketLocked(type, session, generation, flags, payload,
                          descriptors);
}

std::optional<uint64_t> T1OSDecoderConnection::SendPacketLocked(
    uint16_t type,
    uint64_t session,
    uint64_t generation,
    uint32_t flags,
    base::span<const uint8_t> payload,
    base::span<const int> descriptors) {
  if (payload.size() >
          T1_MEDIA_MAX_CONTROL_BYTES - sizeof(t1_media_message_header) ||
      descriptors.size() > T1_MEDIA_MAX_FRAME_OBJECTS) {
    return std::nullopt;
  }
  std::optional<uint64_t> request = NextRequestLocked();
  if (!request) {
    return std::nullopt;
  }

  t1_media_message_header header = {};
  header.magic = T1_MEDIA_PROTOCOL_MAGIC;
  header.version = T1_MEDIA_PROTOCOL_VERSION;
  header.type = type;
  header.size = base::checked_cast<uint32_t>(sizeof(header) + payload.size());
  header.session = session;
  header.request = *request;
  header.generation = generation;
  header.flags = flags;

  std::array<iovec, 2> vectors = {};
  vectors[0].iov_base = &header;
  vectors[0].iov_len = sizeof(header);
  vectors[1].iov_base = const_cast<uint8_t*>(payload.data());
  vectors[1].iov_len = payload.size();

  std::array<uint8_t, CMSG_SPACE(sizeof(int) * T1_MEDIA_MAX_FRAME_OBJECTS)>
      control = {};
  msghdr message = {};
  message.msg_iov = vectors.data();
  message.msg_iovlen = payload.empty() ? 1 : 2;
  if (!descriptors.empty()) {
    message.msg_control = control.data();
    message.msg_controllen = CMSG_SPACE(sizeof(int) * descriptors.size());
    cmsghdr* cmsg = CMSG_FIRSTHDR(&message);
    cmsg->cmsg_level = SOL_SOCKET;
    cmsg->cmsg_type = SCM_RIGHTS;
    cmsg->cmsg_len = CMSG_LEN(sizeof(int) * descriptors.size());
    UNSAFE_BUFFERS(std::memcpy(CMSG_DATA(cmsg), descriptors.data(),
                               sizeof(int) * descriptors.size()));
  }

  {
    base::AutoLock state_lock(state_lock_);
    if (disconnected_) {
      return std::nullopt;
    }
  }
  const ssize_t sent = HANDLE_EINTR(
      sendmsg(socket_.get(), &message, MSG_NOSIGNAL | MSG_DONTWAIT));
  if (sent != static_cast<ssize_t>(header.size)) {
    PLOG(ERROR) << "T1MD sendmsg failed";
    NotifyDisconnect();
    return std::nullopt;
  }
  return request;
}

std::optional<uint64_t> T1OSDecoderConnection::NextRequestLocked() {
  if (request_ids_exhausted_ || next_request_ == 0) {
    return std::nullopt;
  }
  const uint64_t request = next_request_;
  if (next_request_ == std::numeric_limits<uint64_t>::max()) {
    request_ids_exhausted_ = true;
  } else {
    ++next_request_;
  }
  return request;
}

bool T1OSDecoderConnection::NoteFrameReady() {
  base::AutoLock lock(state_lock_);
  const size_t maximum =
      std::min(static_cast<size_t>(capabilities_.maximum_in_flight_frames),
               static_cast<size_t>(T1_MEDIA_MAX_IN_FLIGHT_FRAMES));
  if (disconnected_ || maximum == 0 || in_flight_frames_ >= maximum) {
    return false;
  }
  ++in_flight_frames_;
  return true;
}

bool T1OSDecoderConnection::HasFrameCredit(
    size_t reserved_decode_frames) const {
  base::AutoLock lock(state_lock_);
  const size_t maximum =
      std::min(static_cast<size_t>(capabilities_.maximum_in_flight_frames),
               static_cast<size_t>(T1_MEDIA_MAX_IN_FLIGHT_FRAMES));
  return !disconnected_ && ready_ && maximum > in_flight_frames_ &&
         reserved_decode_frames < maximum - in_flight_frames_;
}

void T1OSDecoderConnection::ReleaseFrame(uint64_t session,
                                         uint64_t generation,
                                         uint64_t frame_id) {
  t1_media_release release = {
      .frame_id = frame_id,
      .flags = 0,
      .reserved = 0,
  };
  Send(T1_MEDIA_RELEASE, session, generation, /*flags=*/0,
       base::byte_span_from_ref(release));
  FrameCreditCB frame_credit_cb;
  {
    base::AutoLock lock(state_lock_);
    if (in_flight_frames_ > 0) {
      --in_flight_frames_;
      frame_credit_cb = frame_credit_cb_;
    }
  }
  if (frame_credit_cb) {
    owner_task_runner_->PostTask(FROM_HERE, std::move(frame_credit_cb));
  }
  MaybeStartDestroy();
}

void T1OSDecoderConnection::ReleaseUntrackedFrame(uint64_t session,
                                                  uint64_t generation,
                                                  uint64_t frame_id) {
  CHECK_NE(frame_id, 0u);
  t1_media_release release = {
      .frame_id = frame_id,
      .flags = 0,
      .reserved = 0,
  };
  Send(T1_MEDIA_RELEASE, session, generation, /*flags=*/0,
       base::byte_span_from_ref(release));
}

void T1OSDecoderConnection::BeginRecycle(uint64_t session,
                                         uint64_t generation,
                                         RecycleCB recycle_cb) {
  {
    base::AutoLock lock(state_lock_);
    packet_cb_.Reset();
    disconnect_cb_.Reset();
    frame_credit_cb_.Reset();
    CHECK(recycle_cb_.is_null());
    recycle_session_ = session;
    recycle_generation_ = generation;
    recycle_cb_ = std::move(recycle_cb);
  }
  MaybeStartDestroy();
}

bool T1OSDecoderConnection::SendHello() {
  base::AutoLock send_lock(send_lock_);
  return SendHelloLocked();
}

bool T1OSDecoderConnection::SendHelloLocked() {
  const uint32_t required_features = RequiredFeaturesForProcess();
  if (required_features == 0) {
    return false;
  }
  t1_media_hello hello = {
      .minimum_version = T1_MEDIA_PROTOCOL_VERSION,
      .maximum_version = T1_MEDIA_PROTOCOL_VERSION,
      .required_features = required_features,
      .maximum_frame_objects = T1_MEDIA_MAX_FRAME_OBJECTS,
      .maximum_frame_layers = T1_MEDIA_MAX_FRAME_LAYERS,
      .maximum_planes_per_layer = T1_MEDIA_MAX_PLANES_PER_LAYER,
      .reserved = 0,
  };
  std::optional<uint64_t> request = NextRequestLocked();
  if (!request) {
    return false;
  }
  {
    base::AutoLock lock(state_lock_);
    hello_request_ = *request;
  }

  // SendPacketLocked normally allocates its own ID. Build HELLO here so the
  // request recorded above and the packet are ordered under one send lock.
  t1_media_message_header header = {};
  header.magic = T1_MEDIA_PROTOCOL_MAGIC;
  header.version = T1_MEDIA_PROTOCOL_VERSION;
  header.type = T1_MEDIA_HELLO;
  header.size = sizeof(header) + sizeof(hello);
  header.session = 0;
  header.request = *request;
  header.generation = 0;
  std::array<iovec, 2> vectors = {
      iovec{.iov_base = &header, .iov_len = sizeof(header)},
      iovec{.iov_base = &hello, .iov_len = sizeof(hello)}};
  msghdr message = {};
  message.msg_iov = vectors.data();
  message.msg_iovlen = vectors.size();
  const ssize_t sent = HANDLE_EINTR(
      sendmsg(socket_.get(), &message, MSG_NOSIGNAL | MSG_DONTWAIT));
  if (sent != static_cast<ssize_t>(header.size)) {
    PLOG(ERROR) << "T1MD HELLO sendmsg failed";
    NotifyDisconnect();
    return false;
  }
  return true;
}

bool T1OSDecoderConnection::ValidateCapabilitiesPacket(
    const T1OSDecoderPacket& packet,
    t1_media_capabilities* capabilities,
    uint64_t* session) const {
  uint64_t expected_request = 0;
  {
    base::AutoLock lock(state_lock_);
    expected_request = hello_request_;
  }
  if (packet.header.type != T1_MEDIA_CAPABILITIES ||
      packet.header.request != expected_request || packet.header.session == 0 ||
      packet.header.generation != 0 || packet.header.flags != 0 ||
      packet.payload.size() != sizeof(t1_media_capabilities) ||
      !packet.descriptors.empty()) {
    return false;
  }
  std::copy(packet.payload.begin(), packet.payload.end(),
            base::byte_span_from_ref(*capabilities).begin());
  if (!HasRequiredCapabilities(*capabilities)) {
    LOG(ERROR) << "T1MD service does not satisfy required capabilities";
    return false;
  }
  *session = packet.header.session;
  return true;
}

std::optional<T1OSDecoderPacket>
T1OSDecoderConnection::ReceivePacketBlocking() {
  std::array<uint8_t, T1_MEDIA_MAX_CONTROL_BYTES> bytes = {};
  std::array<uint8_t, CMSG_SPACE(sizeof(int) * T1_MEDIA_MAX_FRAME_OBJECTS)>
      control = {};
  iovec vector = {.iov_base = bytes.data(), .iov_len = bytes.size()};
  msghdr message = {};
  message.msg_iov = &vector;
  message.msg_iovlen = 1;
  message.msg_control = control.data();
  message.msg_controllen = control.size();

  const ssize_t received =
      HANDLE_EINTR(recvmsg(socket_.get(), &message, MSG_CMSG_CLOEXEC));
  if (received <= 0) {
    return std::nullopt;
  }

  T1OSDecoderPacket packet;
  bool descriptor_error = false;
  for (cmsghdr* cmsg = CMSG_FIRSTHDR(&message); cmsg;
       cmsg = CMSG_NXTHDR(&message, cmsg)) {
    if (cmsg->cmsg_level != SOL_SOCKET || cmsg->cmsg_type != SCM_RIGHTS ||
        cmsg->cmsg_len < CMSG_LEN(0)) {
      continue;
    }
    const size_t count = (cmsg->cmsg_len - CMSG_LEN(0)) / sizeof(int);
    const int* descriptors = reinterpret_cast<const int*>(CMSG_DATA(cmsg));
    if (count > T1_MEDIA_MAX_FRAME_OBJECTS) {
      descriptor_error = true;
      continue;
    }
    for (int descriptor : UNSAFE_BUFFERS(base::span(descriptors, count))) {
      // Take ownership immediately, before validating any other packet field.
      // This guarantees all installed SCM_RIGHTS descriptors close on every
      // error path, including MSG_CTRUNC and malformed headers.
      packet.descriptors.emplace_back(descriptor);
    }
    if (packet.descriptors.size() > T1_MEDIA_MAX_FRAME_OBJECTS) {
      descriptor_error = true;
    }
  }
  if ((message.msg_flags & (MSG_TRUNC | MSG_CTRUNC)) != 0 || descriptor_error ||
      received < static_cast<ssize_t>(sizeof(t1_media_message_header))) {
    LOG(ERROR) << "T1MD packet was truncated";
    return std::nullopt;
  }

  std::copy_n(bytes.begin(), sizeof(packet.header),
              base::byte_span_from_ref(packet.header).begin());
  if (packet.header.magic != T1_MEDIA_PROTOCOL_MAGIC ||
      packet.header.version != T1_MEDIA_PROTOCOL_VERSION ||
      packet.header.size != static_cast<uint32_t>(received) ||
      packet.header.size > T1_MEDIA_MAX_CONTROL_BYTES) {
    LOG(ERROR) << "T1MD packet header failed validation";
    return std::nullopt;
  }
  packet.payload.assign(bytes.begin() + sizeof(packet.header),
                        bytes.begin() + received);
  return packet;
}

bool T1OSDecoderConnection::StartReader() {
  {
    base::AutoLock lock(state_lock_);
    if (reader_started_) {
      return true;
    }
    reader_started_ = true;
  }
  if (!reader_thread_.Start()) {
    return false;
  }
  reader_thread_.task_runner()->PostTask(
      FROM_HERE, base::BindOnce(&T1OSDecoderConnection::ReadLoop,
                                base::RetainedRef(this)));
  return true;
}

void T1OSDecoderConnection::ReadLoop() {
  for (;;) {
    std::optional<T1OSDecoderPacket> packet = ReceivePacketBlocking();
    if (!packet) {
      NotifyDisconnect();
      break;
    }
    if (HandleInternalPacket(&*packet)) {
      continue;
    }
    bool queue_packet = false;
    PacketCB callback;
    {
      base::AutoLock lock(state_lock_);
      if (!disconnected_ && queued_packets_ < kMaximumQueuedPackets &&
          packet->descriptors.size() <=
              kMaximumQueuedDescriptors - queued_descriptors_ &&
          packet_cb_) {
        ++queued_packets_;
        queued_descriptors_ += packet->descriptors.size();
        callback = packet_cb_;
        queue_packet = true;
      }
    }
    if (!queue_packet) {
      LOG(ERROR) << "T1MD worker exceeded Chromium delivery credits";
      NotifyDisconnect();
      break;
    }
    owner_task_runner_->PostTask(
        FROM_HERE, base::BindOnce(&T1OSDecoderConnection::DeliverPacket,
                                  base::RetainedRef(this), std::move(callback),
                                  std::move(*packet)));
  }
  // shutdown() wakes recvmsg(), but only close releases SCM_RIGHTS still
  // queued in the kernel. Close on the reader after its final receive and
  // behind send_lock_ so the descriptor cannot be reused beneath sendmsg().
  base::AutoLock send_lock(send_lock_);
  base::AutoLock socket_lock(socket_lifecycle_lock_);
  socket_.reset();
}

void T1OSDecoderConnection::DeliverPacket(PacketCB callback,
                                          T1OSDecoderPacket packet) {
  CHECK(owner_task_runner_->RunsTasksInCurrentSequence());
  bool invalid_credit = false;
  {
    base::AutoLock lock(state_lock_);
    if (queued_packets_ == 0 ||
        queued_descriptors_ < packet.descriptors.size()) {
      invalid_credit = true;
    } else {
      --queued_packets_;
      queued_descriptors_ -= packet.descriptors.size();
    }
  }
  if (invalid_credit) {
    NotifyDisconnect();
    return;
  }
  if (callback) {
    callback.Run(std::move(packet));
  }
  MaybeStartDestroy();
}

bool T1OSDecoderConnection::HandleInternalPacket(T1OSDecoderPacket* packet) {
  uint64_t destroy_request = 0;
  bool awaiting_capabilities = false;
  {
    base::AutoLock lock(state_lock_);
    destroy_request = destroy_request_;
    awaiting_capabilities = awaiting_post_destroy_capabilities_;
  }

  if (destroy_request != 0) {
    t1_media_result result = {};
    uint64_t expected_session = 0;
    uint64_t expected_generation = 0;
    {
      base::AutoLock lock(state_lock_);
      expected_session = recycle_session_;
      expected_generation = recycle_generation_;
    }
    if (packet->header.type != T1_MEDIA_DESTROY ||
        packet->header.request != destroy_request ||
        packet->header.session != expected_session ||
        packet->header.generation != expected_generation ||
        packet->header.flags != 0 || packet->payload.size() != sizeof(result) ||
        !packet->descriptors.empty()) {
      NotifyDisconnect();
      return true;
    }
    std::copy(packet->payload.begin(), packet->payload.end(),
              base::byte_span_from_ref(result).begin());
    if (result.status != T1_MEDIA_STATUS_OK || result.reserved != 0) {
      NotifyDisconnect();
      return true;
    }
    StartPostDestroyHandshake();
    return true;
  }

  if (awaiting_capabilities) {
    t1_media_capabilities capabilities = {};
    t1_media_capabilities expected_capabilities = {};
    uint64_t session = 0;
    if (packet->header.type != T1_MEDIA_CAPABILITIES ||
        !ValidateCapabilitiesPacket(*packet, &capabilities, &session)) {
      NotifyDisconnect();
      return true;
    }
    {
      base::AutoLock lock(state_lock_);
      expected_capabilities = capabilities_;
    }
    if (base::byte_span_from_ref(capabilities) !=
        base::byte_span_from_ref(expected_capabilities)) {
      LOG(ERROR) << "T1MD capabilities changed while recycling";
      NotifyDisconnect();
      return true;
    }
    {
      base::AutoLock lock(state_lock_);
      capabilities_ = capabilities;
      session_ = session;
      hello_request_ = 0;
      awaiting_post_destroy_capabilities_ = false;
      ready_ = true;
    }
    FinishRecycleAfterHandshake();
    return true;
  }
  return false;
}

void T1OSDecoderConnection::NotifyDisconnect() {
  DisconnectCB callback;
  {
    base::AutoLock lock(state_lock_);
    if (disconnected_) {
      return;
    }
    disconnected_ = true;
    ready_ = false;
    callback = std::move(disconnect_cb_);
    packet_cb_.Reset();
    frame_credit_cb_.Reset();
  }
  // Wake a reader blocked in recvmsg(). Merely marking the connection
  // disconnected would leave its reader-thread RetainedRef and native session
  // alive forever when a DESTROY acknowledgement is rejected.
  {
    base::AutoLock socket_lock(socket_lifecycle_lock_);
    if (socket_.is_valid()) {
      shutdown(socket_.get(), SHUT_RDWR);
    }
  }
  if (callback) {
    owner_task_runner_->PostTask(FROM_HERE, std::move(callback));
  }
}

void T1OSDecoderConnection::MaybeStartDestroy() {
  uint64_t session = 0;
  uint64_t generation = 0;

  // Serialize eligibility and request allocation. ReleaseFrame() can run on a
  // SharedImage destruction sequence while DeliverPacket() runs on the owner
  // sequence; checking only before taking send_lock_ lets both send DESTROY.
  // The lock order matches SendPacketLocked(): send_lock_ then state_lock_.
  base::AutoLock send_lock(send_lock_);
  std::optional<uint64_t> request;
  {
    base::AutoLock lock(state_lock_);
    if (disconnected_ || in_flight_frames_ != 0 || recycle_cb_.is_null() ||
        queued_packets_ != 0 || destroy_request_ != 0 ||
        awaiting_post_destroy_capabilities_) {
      return;
    }
    session = recycle_session_;
    generation = recycle_generation_;
    request = NextRequestLocked();
    if (request) {
      destroy_request_ = *request;
      ready_ = false;
    }
  }
  if (!request) {
    NotifyDisconnect();
    return;
  }
  t1_media_message_header header = {};
  header.magic = T1_MEDIA_PROTOCOL_MAGIC;
  header.version = T1_MEDIA_PROTOCOL_VERSION;
  header.type = T1_MEDIA_DESTROY;
  header.size = sizeof(header);
  header.session = session;
  header.request = *request;
  header.generation = generation;
  iovec vector = {.iov_base = &header, .iov_len = sizeof(header)};
  msghdr message = {};
  message.msg_iov = &vector;
  message.msg_iovlen = 1;
  const ssize_t sent = HANDLE_EINTR(
      sendmsg(socket_.get(), &message, MSG_NOSIGNAL | MSG_DONTWAIT));
  if (sent != static_cast<ssize_t>(sizeof(header))) {
    NotifyDisconnect();
    return;
  }
  owner_task_runner_->PostDelayedTask(
      FROM_HERE,
      base::BindOnce(&T1OSDecoderConnection::OnRecycleTimeout,
                     base::RetainedRef(this), *request,
                     /*waiting_for_capabilities=*/false),
      kDestroyTimeout);
}

void T1OSDecoderConnection::StartPostDestroyHandshake() {
  {
    base::AutoLock lock(state_lock_);
    destroy_request_ = 0;
    session_ = 0;
    ready_ = false;
    awaiting_post_destroy_capabilities_ = true;
  }
  if (!SendHello()) {
    NotifyDisconnect();
    return;
  }
  uint64_t request = 0;
  {
    base::AutoLock lock(state_lock_);
    request = hello_request_;
  }
  owner_task_runner_->PostDelayedTask(
      FROM_HERE,
      base::BindOnce(&T1OSDecoderConnection::OnRecycleTimeout,
                     base::RetainedRef(this), request,
                     /*waiting_for_capabilities=*/true),
      kRehelloTimeout);
}

void T1OSDecoderConnection::OnRecycleTimeout(uint64_t request,
                                             bool waiting_for_capabilities) {
  bool timed_out = false;
  {
    base::AutoLock lock(state_lock_);
    timed_out =
        waiting_for_capabilities
            ? awaiting_post_destroy_capabilities_ && hello_request_ == request
            : destroy_request_ == request;
  }
  if (timed_out) {
    LOG(ERROR) << "T1MD recycle handshake timed out";
    NotifyDisconnect();
  }
}

void T1OSDecoderConnection::FinishRecycleAfterHandshake() {
  RecycleCB callback;
  bool invalid_state = false;
  {
    base::AutoLock lock(state_lock_);
    if (!ready_ || awaiting_post_destroy_capabilities_ ||
        recycle_cb_.is_null()) {
      invalid_state = true;
    } else {
      callback = std::move(recycle_cb_);
      recycle_session_ = 0;
      recycle_generation_ = 0;
    }
  }
  if (invalid_state) {
    NotifyDisconnect();
    return;
  }
  owner_task_runner_->PostTask(
      FROM_HERE, base::BindOnce(std::move(callback), base::RetainedRef(this)));
}

T1OSDecoderConnectionPool& T1OSDecoderConnectionPool::GetInstance() {
  static base::NoDestructor<T1OSDecoderConnectionPool> instance;
  return *instance;
}

T1OSDecoderConnectionPool::T1OSDecoderConnectionPool() = default;
T1OSDecoderConnectionPool::~T1OSDecoderConnectionPool() = default;

bool T1OSDecoderConnectionPool::IsAvailable() {
  Initialize();
  base::AutoLock lock(lock_);
  return supported_;
}

SupportedVideoDecoderConfigs T1OSDecoderConnectionPool::GetSupportedConfigs() {
  if (!IsAvailable()) {
    return {};
  }

  t1_media_capabilities capabilities = {};
  {
    base::AutoLock lock(lock_);
    capabilities = capabilities_;
  }
  return T1OSConfigsFromCapabilities(capabilities);
}

SupportedVideoDecoderConfigs T1OSConfigsFromCapabilities(
    const t1_media_capabilities& capabilities) {
  SupportedVideoDecoderConfigs configs;
  for (const auto& profile :
       base::span(capabilities.profiles).first(capabilities.profile_count)) {
    std::optional<VideoCodecProfile> chromium_profile =
        T1OSProfileToChromiumProfile(profile.profile);
    if (!chromium_profile ||
        !ProfileMatchesCodec(profile.profile, profile.codec) ||
        !ProfileHasUsableOutput(profile) ||
        profile.minimum_width == 0 || profile.minimum_height == 0 ||
        profile.maximum_width < profile.minimum_width ||
        profile.maximum_height < profile.minimum_height ||
        profile.maximum_width >
            static_cast<uint32_t>(std::numeric_limits<int>::max()) ||
        profile.maximum_height >
            static_cast<uint32_t>(std::numeric_limits<int>::max())) {
      continue;
    }
    configs.emplace_back(
        *chromium_profile, *chromium_profile,
        gfx::Size(base::checked_cast<int>(profile.minimum_width),
                  base::checked_cast<int>(profile.minimum_height)),
        gfx::Size(base::checked_cast<int>(profile.maximum_width),
                  base::checked_cast<int>(profile.maximum_height)),
        /*allow_encrypted=*/false, /*require_encrypted=*/false);
  }
  return configs;
}

scoped_refptr<T1OSDecoderConnection> T1OSDecoderConnectionPool::Acquire() {
  if (!IsAvailable()) {
    return nullptr;
  }
  base::AutoLock lock(lock_);
  while (!available_.empty()) {
    scoped_refptr<T1OSDecoderConnection> connection =
        std::move(available_.back());
    available_.pop_back();
    if (connection->is_ready()) {
      return connection;
    }
  }
  LOG(WARNING) << "T1OSVideoDecoder connection pool exhausted";
  return nullptr;
}

size_t T1OSDecoderConnectionPool::available_for_testing() const {
  base::AutoLock lock(lock_);
  return available_.size();
}

void T1OSDecoderConnectionPool::Initialize() {
  {
    base::AutoLock lock(lock_);
    if (initialized_) {
      return;
    }
    initialized_ = true;
  }
  if (!base::FeatureList::IsEnabled(kT1OSVideoDecoder)) {
    return;
  }

  std::vector<scoped_refptr<T1OSDecoderConnection>> connections;
  connections.reserve(kT1OSMediaDecodeDescriptorPoolSize);
  for (size_t index = 0; index < kT1OSMediaDecodeDescriptorPoolSize; ++index) {
    base::MemoryMappedFile::Region region;
    const std::string key =
        base::StringPrintf("%s%zu", kT1OSMediaDecodeDescriptorPrefix, index);
    base::ScopedFD socket =
        base::FileDescriptorStore::GetInstance().MaybeTakeFD(key, &region);
    if (!socket.is_valid()) {
      break;
    }
    auto connection = base::MakeRefCounted<T1OSDecoderConnection>(
        std::move(socket), base::SequencedTaskRunner::GetCurrentDefault());
    // The native worker has a finite pre-HELLO timeout. Eagerly authenticate
    // every preconnected descriptor so unused slots remain reusable for the
    // lifetime of this GPU process.
    if (connection->EnsureHandshake()) {
      connections.push_back(std::move(connection));
    }
  }
  {
    base::AutoLock lock(lock_);
    if (connections.size() == kT1OSMediaDecodeDescriptorPoolSize) {
      const t1_media_capabilities expected =
          connections.front()->capabilities();
      const bool identical = std::all_of(
          connections.begin() + 1, connections.end(),
          [&expected](const auto& connection) {
            const t1_media_capabilities actual = connection->capabilities();
            return base::byte_span_from_ref(actual) ==
                   base::byte_span_from_ref(expected);
          });
      if (identical) {
        capabilities_ = expected;
        supported_ = true;
      } else {
        LOG(ERROR) << "T1OSVideoDecoder broker capabilities disagree";
        connections.clear();
      }
    } else {
      LOG(ERROR) << "T1OSVideoDecoder requires all "
                 << kT1OSMediaDecodeDescriptorPoolSize
                 << " authenticated broker connections";
      connections.clear();
    }
    available_ = std::move(connections);
  }
}

void T1OSDecoderConnectionPool::Recycle(
    scoped_refptr<T1OSDecoderConnection> connection) {
  CHECK(connection);
  connection->ClearClient();
  if (!connection->is_ready()) {
    return;
  }
  const t1_media_capabilities capabilities = connection->capabilities();
  {
    base::AutoLock lock(lock_);
    if (supported_ && base::byte_span_from_ref(capabilities) ==
                          base::byte_span_from_ref(capabilities_)) {
      available_.push_back(std::move(connection));
      return;
    }
  }
  connection->Abandon();
}

std::optional<VideoCodecProfile> T1OSProfileToChromiumProfile(
    uint32_t profile) {
  switch (profile) {
    case T1_MEDIA_PROFILE_H264_BASELINE:
      return H264PROFILE_BASELINE;
    case T1_MEDIA_PROFILE_H264_MAIN:
      return H264PROFILE_MAIN;
    case T1_MEDIA_PROFILE_H264_HIGH:
      return H264PROFILE_HIGH;
    case T1_MEDIA_PROFILE_VP8_ANY:
      return VP8PROFILE_ANY;
    case T1_MEDIA_PROFILE_VP9_0:
      return VP9PROFILE_PROFILE0;
    case T1_MEDIA_PROFILE_VP9_1:
      return VP9PROFILE_PROFILE1;
    case T1_MEDIA_PROFILE_VP9_2:
      return VP9PROFILE_PROFILE2;
    case T1_MEDIA_PROFILE_VP9_3:
      return VP9PROFILE_PROFILE3;
    case T1_MEDIA_PROFILE_HEVC_MAIN:
      return HEVCPROFILE_MAIN;
    case T1_MEDIA_PROFILE_HEVC_MAIN10:
      return HEVCPROFILE_MAIN10;
    case T1_MEDIA_PROFILE_AV1_MAIN:
      return AV1PROFILE_PROFILE_MAIN;
    default:
      return std::nullopt;
  }
}

}  // namespace media
