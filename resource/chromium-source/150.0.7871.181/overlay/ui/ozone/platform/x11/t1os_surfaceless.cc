// Copyright 2026 The One OS Authors
// Use of this source code is governed by a BSD-style license.

#include "ui/ozone/platform/x11/t1os_surfaceless.h"

#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <unistd.h>

#include <algorithm>
#include <array>
#include <cstring>
#include <limits>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include <drm_fourcc.h>
#include <gbm.h>

#include "base/compiler_specific.h"
#include "base/file_descriptor_store.h"
#include "base/functional/bind.h"
#include "base/json/json_reader.h"
#include "base/logging.h"
#include "base/posix/eintr_wrapper.h"
#include "base/strings/strcat.h"
#include "base/strings/string_number_conversions.h"
#include "base/task/sequenced_task_runner.h"
#include "base/threading/thread_restrictions.h"
#include "base/time/time.h"
#include "ui/gfx/linux/gbm_support_x11.h"
#include "ui/gfx/presentation_feedback.h"
#include "ui/gfx/swap_result.h"
#include "ui/gl/egl_util.h"
#include "ui/gl/gl_bindings.h"
#include "ui/gl/gl_context.h"

namespace ui {

// ScopedAllowBlocking has a deliberately narrow friend for GBM surface
// teardown. Chromium's standard DRM GBM implementation uses this same scope:
// stopping an I/O watcher must join its thread before the surface is freed.
class ScopedAllowBlockingForGbmSurface : public base::ScopedAllowBlocking {};

namespace {

constexpr size_t kMaximumControlPacket = 4096;
constexpr size_t kMaximumDmaBufObjects = 4;
constexpr size_t kMaximumInFlightFrames = 3;
constexpr size_t kMaximumRetiredGenerations = 4;
constexpr uint64_t kMaximumExportBytes = 512ull * 1024ull * 1024ull;
constexpr uint32_t kGbmUsage =
    GBM_BO_USE_SCANOUT | GBM_BO_USE_RENDERING;
constexpr char kPresentationDescriptor[] = "t1os-presentation";
constexpr base::TimeDelta kDestroyDrainTimeout = base::Milliseconds(50);

std::optional<uint64_t> PositiveInteger(const base::DictValue& message,
                                        std::string_view name) {
  if (const std::optional<int> value = message.FindInt(name);
      value && *value > 0) {
    return static_cast<uint64_t>(*value);
  }
  const std::string* text = message.FindString(name);
  uint64_t value = 0;
  if (text && base::StringToUint64(*text, &value) && value > 0) {
    return value;
  }
  return std::nullopt;
}

std::optional<uint64_t> FrameNumber(const base::DictValue& message) {
  return PositiveInteger(message, "frame");
}

std::optional<uint64_t> GenerationNumber(const base::DictValue& message) {
  return PositiveInteger(message, "generation");
}

}  // namespace

// static
scoped_refptr<T1OSGbmSurface> T1OSGbmSurface::Create(
    gl::GLDisplayEGL* display,
    gfx::AcceleratedWidget owner_widget) {
  base::MemoryMappedFile::Region region;
  base::ScopedFD socket = base::FileDescriptorStore::GetInstance().MaybeTakeFD(
      kPresentationDescriptor, &region);
  if (!socket.is_valid()) {
    LOG(ERROR) << "T1OS_PRESENTATION_BRIDGE transport descriptor unavailable "
               << "owner_widget=" << owner_widget
               << " (a presentation descriptor has exactly one widget owner)";
    return nullptr;
  }
  scoped_refptr<T1OSGbmSurface> created =
      new T1OSGbmSurface(display, owner_widget, std::move(socket));
  if (!created->Initialize(gl::GLSurfaceFormat())) {
    return nullptr;
  }
  return created;
}

T1OSGbmSurface::T1OSGbmSurface(gl::GLDisplayEGL* display,
                               gfx::AcceleratedWidget owner_widget,
                               base::ScopedFD socket)
    : gl::GLSurfaceEGL(display),
      owner_widget_(owner_widget),
      socket_(std::move(socket)),
      owning_task_runner_(base::SequencedTaskRunner::GetCurrentDefault()) {}

T1OSGbmSurface::~T1OSGbmSurface() {
  Destroy();
}

bool T1OSGbmSurface::Initialize(gl::GLSurfaceFormat format) {
  format_ = format;
  if (GetEGLDisplay() == EGL_NO_DISPLAY || !InitializeTransport() ||
      !ChooseGbmConfig() || !CreateGbmSurface(size_)) {
    Destroy();
    return false;
  }
  LOG(INFO) << "T1OS_PRESENTATION_BRIDGE transport=rgb-gbm-dmabuf-v1 "
               "queue_depth="
            << kMaximumInFlightFrames
            << " producer_sync=glFinish consumer_sync=glFinish "
               "native_sync_file=0 per_widget_owner=1 owner_widget="
            << owner_widget_;
  return true;
}

bool T1OSGbmSurface::InitializeTransport() {
  if (transport_initialized_) {
    return !failed_;
  }
  weak_this_ = weak_factory_.GetWeakPtr();
  const int flags = fcntl(socket_.get(), F_GETFL);
  if (flags < 0 ||
      HANDLE_EINTR(fcntl(socket_.get(), F_SETFL, flags | O_NONBLOCK)) < 0) {
    PLOG(ERROR) << "T1OS_PRESENTATION_BRIDGE could not set nonblocking mode";
    return false;
  }
  base::Thread::Options io_options(base::MessagePumpType::IO, 0);
  if (!presentation_io_thread_.StartWithOptions(std::move(io_options))) {
    LOG(ERROR) << "T1OS_PRESENTATION_BRIDGE could not start I/O watcher";
    return false;
  }
  file_descriptor_watcher_ = std::make_unique<base::FileDescriptorWatcher>(
      presentation_io_thread_.task_runner());
  if (!StartReadWatcher()) {
    return false;
  }
  transport_initialized_ = read_watcher_ != nullptr;
  return transport_initialized_;
}

bool T1OSGbmSurface::StartReadWatcher() {
  read_watcher_ = base::FileDescriptorWatcher::WatchReadable(
      socket_.get(),
      base::BindRepeating(&T1OSGbmSurface::OnReadable, base::Unretained(this)));
  return read_watcher_ != nullptr;
}

bool T1OSGbmSurface::ChooseGbmConfig() {
  const EGLint attributes[] = {EGL_RED_SIZE,
                               8,
                               EGL_GREEN_SIZE,
                               8,
                               EGL_BLUE_SIZE,
                               8,
                               EGL_ALPHA_SIZE,
                               0,
                               EGL_RENDERABLE_TYPE,
                               EGL_OPENGL_ES2_BIT,
                               EGL_SURFACE_TYPE,
                               EGL_WINDOW_BIT,
                               EGL_NONE};
  std::array<EGLConfig, 64> configs = {};
  EGLint count = 0;
  if (eglChooseConfig(GetEGLDisplay(), attributes, configs.data(),
                      static_cast<EGLint>(configs.size()), &count) != EGL_TRUE ||
      count < 1) {
    LOG(ERROR) << "T1OS_PRESENTATION_BRIDGE no EGL GBM window configs: "
               << ui::GetLastEGLErrorString();
    return false;
  }
  for (EGLint index = 0;
       index < count && index < static_cast<EGLint>(configs.size()); ++index) {
    EGLint visual = 0;
    if (eglGetConfigAttrib(GetEGLDisplay(), configs[index],
                           EGL_NATIVE_VISUAL_ID, &visual) == EGL_TRUE &&
        static_cast<uint32_t>(visual) == DRM_FORMAT_XRGB8888) {
      config_ = configs[index];
      return true;
    }
  }
  LOG(ERROR) << "T1OS_PRESENTATION_BRIDGE EGL has no XRGB8888 GBM config";
  return false;
}

bool T1OSGbmSurface::CreateGbmSurface(const gfx::Size& size) {
  if (size.IsEmpty() || size.width() > 8192 || size.height() > 8192) {
    return false;
  }
  gbm_device* device = GBMSupportX11::GetInstance()->GetNativeDevice();
  if (!device) {
    LOG(ERROR) << "T1OS_PRESENTATION_BRIDGE brokered GBM device unavailable";
    return false;
  }
  gbm_surface_ = gbm_surface_create(device, size.width(), size.height(),
                                    DRM_FORMAT_XRGB8888, kGbmUsage);
  if (!gbm_surface_) {
    LOG(ERROR) << "T1OS_PRESENTATION_BRIDGE gbm_surface_create failed";
    return false;
  }
  surface_ = eglCreateWindowSurface(
      GetEGLDisplay(), config_,
      reinterpret_cast<EGLNativeWindowType>(gbm_surface_.get()), nullptr);
  if (surface_ == EGL_NO_SURFACE) {
    LOG(ERROR) << "T1OS_PRESENTATION_BRIDGE EGL GBM window surface failed: "
               << ui::GetLastEGLErrorString();
    // GBM is allocated through Chromium's allocator shim on this runtime.
    // Clear the BackupRefPtr slot before the external destroy can free it;
    // otherwise the diagnostic cleanup itself is terminated as a dangling
    // raw_ptr violation and hides the original EGL error.
    gbm_surface* failed_surface = gbm_surface_;
    gbm_surface_ = nullptr;
    gbm_surface_destroy(failed_surface);
    return false;
  }
  size_ = size;
  ++generation_;
  if (generation_ == 0 || !SendConfigure()) {
    LOG(ERROR) << "T1OS_PRESENTATION_BRIDGE could not configure DMA-BUF "
                  "consumer";
    eglDestroySurface(GetEGLDisplay(), surface_);
    surface_ = EGL_NO_SURFACE;
    gbm_surface* unconfigured_surface = gbm_surface_;
    gbm_surface_ = nullptr;
    gbm_surface_destroy(unconfigured_surface);
    return false;
  }
  LOG(INFO) << "T1OS_PRESENTATION_BRIDGE configured generation="
            << generation_ << " size=" << size_.ToString()
            << " format=XR24 queue_depth=" << kMaximumInFlightFrames;
  return true;
}

bool T1OSGbmSurface::SendPacket(const std::string& packet,
                                const std::vector<int>& descriptors) {
  if (!socket_.is_valid() || descriptors.size() > kMaximumDmaBufObjects) {
    return false;
  }
  iovec vector = {.iov_base = const_cast<char*>(packet.data()),
                  .iov_len = packet.size()};
  msghdr message = {};
  message.msg_iov = &vector;
  message.msg_iovlen = 1;
  std::array<uint8_t,
             CMSG_SPACE(sizeof(int) * kMaximumDmaBufObjects)>
      control = {};
  if (!descriptors.empty()) {
    const size_t descriptor_bytes = descriptors.size() * sizeof(int);
    message.msg_control = control.data();
    message.msg_controllen = CMSG_SPACE(descriptor_bytes);
    cmsghdr* cmsg = CMSG_FIRSTHDR(&message);
    cmsg->cmsg_level = SOL_SOCKET;
    cmsg->cmsg_type = SCM_RIGHTS;
    cmsg->cmsg_len = CMSG_LEN(descriptor_bytes);
    UNSAFE_BUFFERS(std::memcpy(CMSG_DATA(cmsg), descriptors.data(),
                               descriptor_bytes));
  }
  const ssize_t sent = HANDLE_EINTR(
      sendmsg(socket_.get(), &message, MSG_NOSIGNAL | MSG_DONTWAIT));
  return sent == static_cast<ssize_t>(packet.size());
}

bool T1OSGbmSurface::SendConfigure() {
  return SendPacket(base::StrCat(
      {"{\"op\":\"configure\",\"transport\":\"rgb-gbm-dmabuf-v1\"",
       ",\"generation\":", base::NumberToString(generation_),
       ",\"owner_widget\":\"",
       base::NumberToString(static_cast<uint64_t>(owner_widget_)), "\"",
       ",\"width\":", base::NumberToString(size_.width()),
       ",\"height\":", base::NumberToString(size_.height()),
       ",\"fourcc\":", base::NumberToString(DRM_FORMAT_XRGB8888),
       ",\"queue_depth\":", base::NumberToString(kMaximumInFlightFrames),
       ",\"sync_mode\":\"glfinish-producer-consumer\"}"}));
}

bool T1OSGbmSurface::SendFrame(uint64_t frame, gbm_bo* buffer) {
  if (!buffer || gbm_bo_get_format(buffer) != DRM_FORMAT_XRGB8888) {
    return false;
  }
  const uint32_t stride = gbm_bo_get_stride(buffer);
  if (size_.width() <= 0 ||
      static_cast<uint64_t>(size_.width()) >
          std::numeric_limits<uint32_t>::max() / 4u ||
      stride < static_cast<uint32_t>(size_.width()) * 4u) {
    LOG(ERROR) << "T1OS_PRESENTATION_BRIDGE invalid XRGB DMA-BUF stride="
               << stride << " width=" << size_.width();
    return false;
  }
  const uint64_t calculated_size =
      static_cast<uint64_t>(stride) * static_cast<uint64_t>(size_.height());
  base::ScopedFD descriptor(gbm_bo_get_fd(buffer));
  if (!descriptor.is_valid() || stride == 0 || calculated_size == 0 ||
      calculated_size > kMaximumExportBytes) {
    return false;
  }
  uint64_t object_size = calculated_size;
  struct stat information = {};
  if (fstat(descriptor.get(), &information) == 0 && information.st_size > 0) {
    object_size = std::max(
        object_size, static_cast<uint64_t>(information.st_size));
  }
  if (object_size > kMaximumExportBytes) {
    return false;
  }
  const uint64_t modifier = gbm_bo_get_modifier(buffer);
  if (modifier == DRM_FORMAT_MOD_INVALID) {
    LOG(ERROR) << "T1OS_PRESENTATION_BRIDGE GBM did not expose a modifier";
    return false;
  }
  const std::string packet = base::StrCat(
      {"{\"op\":\"frame\",\"transport\":\"rgb-gbm-dmabuf-v1\"",
       ",\"generation\":", base::NumberToString(generation_),
       ",\"frame\":\"", base::NumberToString(frame), "\"",
       ",\"pts_ns\":0,\"width\":", base::NumberToString(size_.width()),
       ",\"height\":", base::NumberToString(size_.height()),
       ",\"coded_width\":", base::NumberToString(size_.width()),
       ",\"coded_height\":", base::NumberToString(size_.height()),
       ",\"format\":\"drm_prime\",\"export_mode\":\"composed\"",
       ",\"origin\":\"bottom-left\"",
       ",\"sync_mode\":\"glfinish-producer-consumer\"",
       ",\"objects\":[{\"size\":", base::NumberToString(object_size),
       ",\"modifier\":\"", base::NumberToString(modifier), "\"}]",
       ",\"layers\":[{\"width\":", base::NumberToString(size_.width()),
       ",\"height\":", base::NumberToString(size_.height()),
       ",\"fourcc\":", base::NumberToString(DRM_FORMAT_XRGB8888),
       ",\"planes\":[{\"object\":0,\"offset\":0,\"pitch\":",
       base::NumberToString(stride), "}]}]}"});
  return SendPacket(packet, std::vector<int>{descriptor.get()});
}

gbm_bo* T1OSGbmSurface::SwapAndExport(uint64_t frame) {
  size_t current_in_flight = 0;
  for (const auto& [key, pending] : pending_frames_) {
    if (key.first == generation_) {
      ++current_in_flight;
    }
  }
  if (failed_ || !gbm_surface_ || surface_ == EGL_NO_SURFACE || frame == 0 ||
      current_in_flight >= kMaximumInFlightFrames) {
    if (current_in_flight >= kMaximumInFlightFrames) {
      LOG(ERROR) << "T1OS_PRESENTATION_BRIDGE bounded queue full generation="
                 << generation_ << " depth=" << current_in_flight;
    }
    return nullptr;
  }
  if (eglSwapBuffers(GetEGLDisplay(), surface_) != EGL_TRUE) {
    LOG(ERROR) << "T1OS_PRESENTATION_BRIDGE EGL GBM swap failed: "
               << ui::GetLastEGLErrorString();
    return nullptr;
  }

  // No native sync-file is exported by this protocol yet. Finish all producer
  // writes before transferring the DMA-BUF. WindowServer performs the matching
  // finish before releasing ownership back to this process.
  glFinish();
  gbm_bo* buffer = gbm_surface_lock_front_buffer(gbm_surface_);
  if (!buffer) {
    LOG(ERROR) << "T1OS_PRESENTATION_BRIDGE could not lock GBM front buffer";
    return nullptr;
  }
  if (!SendFrame(frame, buffer)) {
    gbm_surface_release_buffer(gbm_surface_, buffer);
    return nullptr;
  }
  return buffer;
}

bool T1OSGbmSurface::Resize(const gfx::Size& size,
                            float scale_factor,
                            const gfx::ColorSpace& color_space,
                            bool has_alpha) {
  if (size == size_) {
    return true;
  }
  if (size.IsEmpty()) {
    return false;
  }
  gl::GLContext* context = gl::GLContext::GetCurrent();
  gl::GLSurface* current_surface = gl::GLSurface::GetCurrent();
  if (!context || current_surface != this) {
    LOG(ERROR) << "T1OS_PRESENTATION_BRIDGE resize without its current context";
    return false;
  }
  glFinish();
  context->ReleaseCurrent(current_surface);
  if (!RetireCurrentGeneration()) {
    context->MakeCurrent(current_surface);
    LOG(ERROR) << "T1OS_PRESENTATION_BRIDGE DMA-BUF generation retirement failed "
                  "during resize";
    return false;
  }
  if (!CreateGbmSurface(size) || !context->MakeCurrent(current_surface)) {
    LOG(ERROR) << "T1OS_PRESENTATION_BRIDGE GBM resize failed";
    return false;
  }
  return true;
}

gfx::SwapResult T1OSGbmSurface::SwapBuffers(PresentationCallback callback,
                                            gfx::FrameData data) {
  const uint64_t frame = next_frame_++;
  gbm_bo* buffer = SwapAndExport(frame);
  if (!buffer) {
    if (callback) {
      std::move(callback).Run(gfx::PresentationFeedback::Failure());
    }
    return gfx::SwapResult::SWAP_FAILED;
  }
  pending_frames_.emplace(
      FrameKey{generation_, frame},
      PendingFrame{/*owner_surface=*/gbm_surface_, /*buffer=*/buffer,
                   /*completion_callback=*/{},
                   std::move(callback), /*presentation_received=*/false,
                   /*presentation_succeeded=*/false});
  return gfx::SwapResult::SWAP_ACK;
}

bool T1OSGbmSurface::SupportsAsyncSwap() {
  return true;
}

void T1OSGbmSurface::SwapBuffersAsync(
    SwapCompletionCallback completion_callback,
    PresentationCallback presentation_callback,
    gfx::FrameData data) {
  const uint64_t frame = next_frame_++;
  gbm_bo* buffer = SwapAndExport(frame);
  if (!buffer) {
    std::move(completion_callback)
        .Run(gfx::SwapCompletionResult(gfx::SwapResult::SWAP_FAILED));
    std::move(presentation_callback).Run(gfx::PresentationFeedback::Failure());
    return;
  }
  pending_frames_.emplace(
      FrameKey{generation_, frame},
      PendingFrame{/*owner_surface=*/gbm_surface_, /*buffer=*/buffer,
                   std::move(completion_callback),
                   std::move(presentation_callback),
                   /*presentation_received=*/false,
                   /*presentation_succeeded=*/false});
}

void T1OSGbmSurface::OnReadable() {
  for (;;) {
    std::array<char, kMaximumControlPacket> packet = {};
    const ssize_t length = HANDLE_EINTR(
        recv(socket_.get(), packet.data(), packet.size(), MSG_DONTWAIT));
    if (length < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
      return;
    }
    if (length <= 0) {
      owning_task_runner_->PostTask(
          FROM_HERE, base::BindOnce(&T1OSGbmSurface::OnTransportFailure,
                                    weak_this_, "peer closed"));
      return;
    }
    // This callback may run on the watcher sequence. It performs only the
    // recv and posts an immutable packet; all generation, GBM, and callback
    // state is touched exclusively on the owning GPU sequence.
    owning_task_runner_->PostTask(
        FROM_HERE,
        base::BindOnce(
            &T1OSGbmSurface::ProcessControlPacket, weak_this_,
            std::string(packet.data(), static_cast<size_t>(length))));
  }
}

void T1OSGbmSurface::ProcessControlPacket(std::string packet) {
  // Completion callbacks may synchronously release Viz's final reference to
  // this surface. Keep it alive through swap and presentation callbacks,
  // including any generation cleanup they trigger.
  scoped_refptr<T1OSGbmSurface> keep_alive(this);
  std::optional<base::DictValue> value =
      base::JSONReader::ReadDict(packet, 0);
  if (!value) {
    OnTransportFailure("invalid control packet");
    return;
  }
  const std::string* operation = value->FindString("op");
  const std::optional<uint64_t> generation = GenerationNumber(*value);
  const std::optional<uint64_t> frame = FrameNumber(*value);
  if (!operation) {
    OnTransportFailure("control packet missing operation");
    return;
  }
  if (*operation == "configured") {
    return;
  }
  if (*operation == "cleared" && generation) {
    HandleCleared(*generation);
    return;
  }
  if ((*operation == "presented" || *operation == "dropped" ||
       *operation == "release") &&
      generation && frame) {
    CompleteFrame(*generation, *frame, *operation == "presented",
                  *operation == "dropped");
    return;
  }
  if (*operation == "error") {
    OnTransportFailure("WindowServer rejected RGB DMA-BUF transport");
  }
}

void T1OSGbmSurface::CompleteFrame(uint64_t generation,
                                   uint64_t frame,
                                   bool presented,
                                   bool dropped) {
  auto found = pending_frames_.find(FrameKey{generation, frame});
  if (found == pending_frames_.end()) {
    return;
  }
  PendingFrame& pending = found->second;
  if ((presented || dropped) && !pending.presentation_received) {
    pending.presentation_received = true;
    pending.presentation_succeeded = presented && !dropped;
    return;
  }
  if (presented || dropped) {
    return;
  }

  // A release is the sole ownership transition. WindowServer has completed
  // its GL read before sending it, so the GBM surface may now recycle this BO.
  gbm_surface* owner_surface = pending.owner_surface;
  gbm_bo* buffer = pending.buffer;
  pending.owner_surface = nullptr;
  pending.buffer = nullptr;
  ReleaseBuffer(owner_surface, buffer);
  SwapCompletionCallback completion = std::move(pending.completion_callback);
  PresentationCallback presentation = std::move(pending.presentation_callback);
  const bool presentation_succeeded =
      pending.presentation_received && pending.presentation_succeeded;
  pending_frames_.erase(found);

  // Viz must observe swap completion before presentation feedback for the same
  // frame. Both callbacks run in order on this surface's owning sequence.
  if (completion) {
    std::move(completion)
        .Run(gfx::SwapCompletionResult(gfx::SwapResult::SWAP_ACK));
  }
  if (presentation_succeeded && presentation) {
    std::move(presentation)
        .Run(gfx::PresentationFeedback(base::TimeTicks::Now(),
                                       base::Seconds(1) / 60,
                                       gfx::PresentationFeedback::kVSync));
  } else if (presentation) {
    std::move(presentation).Run(gfx::PresentationFeedback::Failure());
  }
}

void T1OSGbmSurface::ReleaseBuffer(gbm_surface* owner_surface,
                                   gbm_bo* buffer) {
  if (owner_surface && buffer) {
    gbm_surface_release_buffer(owner_surface, buffer);
  }
}

void T1OSGbmSurface::ReleaseGeneration(uint64_t generation) {
  std::vector<FrameKey> keys;
  for (const auto& [key, pending] : pending_frames_) {
    if (key.first == generation) {
      keys.push_back(key);
    }
  }
  for (const FrameKey& key : keys) {
    auto found = pending_frames_.find(key);
    if (found == pending_frames_.end()) {
      continue;
    }
    PendingFrame pending = std::move(found->second);
    pending_frames_.erase(found);
    gbm_surface* owner_surface = pending.owner_surface;
    gbm_bo* buffer = pending.buffer;
    pending.owner_surface = nullptr;
    pending.buffer = nullptr;
    ReleaseBuffer(owner_surface, buffer);
    if (pending.completion_callback) {
      std::move(pending.completion_callback)
          .Run(gfx::SwapCompletionResult(gfx::SwapResult::SWAP_FAILED));
    }
    if (pending.presentation_callback) {
      std::move(pending.presentation_callback)
          .Run(gfx::PresentationFeedback::Failure());
    }
  }
}

void T1OSGbmSurface::ReleaseAllFrames() {
  std::map<FrameKey, PendingFrame> frames;
  frames.swap(pending_frames_);
  for (auto& [key, pending] : frames) {
    gbm_surface* owner_surface = pending.owner_surface;
    gbm_bo* buffer = pending.buffer;
    pending.owner_surface = nullptr;
    pending.buffer = nullptr;
    ReleaseBuffer(owner_surface, buffer);
    if (pending.completion_callback) {
      std::move(pending.completion_callback)
          .Run(gfx::SwapCompletionResult(gfx::SwapResult::SWAP_FAILED));
    }
    if (pending.presentation_callback) {
      std::move(pending.presentation_callback)
          .Run(gfx::PresentationFeedback::Failure());
    }
  }
}

bool T1OSGbmSurface::RetireCurrentGeneration() {
  if (!gbm_surface_ || surface_ == EGL_NO_SURFACE) {
    return true;
  }
  if (!socket_.is_valid() || generation_ == 0 ||
      retired_generations_.size() >= kMaximumRetiredGenerations) {
    return false;
  }
  if (!SendPacket(base::StrCat({"{\"op\":\"clear\",\"generation\":",
                               base::NumberToString(generation_), "}"}))) {
    LOG(ERROR) << "T1OS_PRESENTATION_BRIDGE could not request DMA-BUF teardown";
    return false;
  }
  retired_generations_.emplace(
      generation_, RetiredGeneration{gbm_surface_, surface_});
  gbm_surface_ = nullptr;
  surface_ = EGL_NO_SURFACE;
  LOG(INFO) << "T1OS_PRESENTATION_BRIDGE retired generation=" << generation_
            << " asynchronously pending_generations="
            << retired_generations_.size();
  return true;
}

void T1OSGbmSurface::HandleCleared(uint64_t generation) {
  if (!retired_generations_.contains(generation)) {
    return;
  }
  // WindowServer sends "cleared" only after destroying every EGLImage for the
  // generation. Any missing release receipt can now be failed locally and the
  // locked BOs safely returned before their GBM surface is destroyed.
  ReleaseGeneration(generation);
  DestroyRetiredGeneration(generation);
  LOG(INFO) << "T1OS_PRESENTATION_BRIDGE generation cleared=" << generation
            << " pending_generations=" << retired_generations_.size();
}

void T1OSGbmSurface::DrainRetiredGenerationsForDestroy() {
  const base::TimeTicks deadline = base::TimeTicks::Now() + kDestroyDrainTimeout;
  while (!retired_generations_.empty() && socket_.is_valid() &&
         base::TimeTicks::Now() < deadline) {
    pollfd wait = {.fd = socket_.get(), .events = POLLIN, .revents = 0};
    const int ready = HANDLE_EINTR(poll(&wait, 1, 2));
    if (ready < 0) {
      break;
    }
    if (ready == 0 || !(wait.revents & (POLLIN | POLLHUP | POLLERR))) {
      continue;
    }
    std::array<char, kMaximumControlPacket> packet = {};
    const ssize_t length = HANDLE_EINTR(
        recv(socket_.get(), packet.data(), packet.size(), MSG_DONTWAIT));
    if (length < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
      continue;
    }
    if (length <= 0) {
      break;
    }
    ProcessControlPacket(
        std::string(packet.data(), static_cast<size_t>(length)));
  }
  if (!retired_generations_.empty()) {
    LOG(WARNING) << "T1OS_PRESENTATION_BRIDGE destroy drain expired after "
                 << kDestroyDrainTimeout.InMilliseconds()
                 << "ms generations=" << retired_generations_.size();
  }
}

void T1OSGbmSurface::DestroyRetiredGeneration(uint64_t generation) {
  auto found = retired_generations_.find(generation);
  if (found == retired_generations_.end()) {
    return;
  }
  RetiredGeneration retired = found->second;
  retired_generations_.erase(found);
  gbm_surface* retired_gbm = retired.gbm;
  retired.gbm = nullptr;
  if (retired.egl != EGL_NO_SURFACE) {
    eglDestroySurface(GetEGLDisplay(), retired.egl);
  }
  if (retired_gbm) {
    gbm_surface_destroy(retired_gbm);
  }
}

void T1OSGbmSurface::DestroyGbmSurface() {
  if (surface_ != EGL_NO_SURFACE) {
    eglDestroySurface(GetEGLDisplay(), surface_);
    surface_ = EGL_NO_SURFACE;
  }
  if (gbm_surface_) {
    gbm_surface* destroyed_surface = gbm_surface_;
    gbm_surface_ = nullptr;
    gbm_surface_destroy(destroyed_surface);
  }
}

void T1OSGbmSurface::Destroy() {
  weak_factory_.InvalidateWeakPtrs();
  read_watcher_.reset();
  file_descriptor_watcher_.reset();
  if (presentation_io_thread_.IsRunning()) {
    // The watcher owns an Unretained callback, so teardown must join it before
    // freeing this surface. Chromium explicitly sanctions this narrow GBM
    // cleanup scope on otherwise non-blocking GPU sequences.
    ScopedAllowBlockingForGbmSurface allow_thread_join;
    presentation_io_thread_.Stop();
  }
  if (!failed_ && gbm_surface_) {
    RetireCurrentGeneration();
    DrainRetiredGenerationsForDestroy();
  }
  ReleaseAllFrames();
  DestroyGbmSurface();
  while (!retired_generations_.empty()) {
    DestroyRetiredGeneration(retired_generations_.begin()->first);
  }
  socket_.reset();
  transport_initialized_ = false;
  InvalidateWeakPtrs();
}

bool T1OSGbmSurface::IsOffscreen() {
  return false;
}

gfx::Size T1OSGbmSurface::GetSize() {
  return size_;
}

void* T1OSGbmSurface::GetHandle() {
  return surface_;
}

void T1OSGbmSurface::OnTransportFailure(const char* reason) {
  if (failed_) {
    return;
  }
  failed_ = true;
  LOG(ERROR) << "T1OS_PRESENTATION_BRIDGE transport failure: " << reason;
  read_watcher_.reset();
  // This callback does not own a proof that this surface's GL context is
  // current. Calling NVIDIA GL dispatch here can itself cause context loss;
  // normal ownership release is synchronized by the consumer before ACK.
  ReleaseAllFrames();
}

// static
scoped_refptr<T1OSAuxiliarySurface> T1OSAuxiliarySurface::Create(
    gl::GLDisplayEGL* display,
    gfx::AcceleratedWidget owner_widget) {
  scoped_refptr<T1OSAuxiliarySurface> created =
      new T1OSAuxiliarySurface(display);
  if (!created->Initialize(gl::GLSurfaceFormat())) {
    return nullptr;
  }
  LOG(ERROR) << "T1OS_PRESENTATION_BRIDGE auxiliary top-level contained "
                "without visible presentation owner_widget="
             << owner_widget;
  return created;
}

T1OSAuxiliarySurface::T1OSAuxiliarySurface(gl::GLDisplayEGL* display)
    : gl::PbufferGLSurfaceEGL(display, gfx::Size(1, 1)) {}

T1OSAuxiliarySurface::~T1OSAuxiliarySurface() = default;

bool T1OSAuxiliarySurface::IsOffscreen() {
  // Viz created this through CreateViewGLSurface. Report view semantics while
  // retaining the same GBM EGLDisplay as the authorized root.
  return false;
}

bool T1OSAuxiliarySurface::SupportsAsyncSwap() {
  return true;
}

gfx::SwapResult T1OSAuxiliarySurface::SwapBuffers(
    PresentationCallback callback,
    gfx::FrameData data) {
  glFlush();
  if (callback) {
    std::move(callback).Run(gfx::PresentationFeedback(
        base::TimeTicks::Now(), base::Seconds(1) / 60,
        gfx::PresentationFeedback::kVSync));
  }
  return gfx::SwapResult::SWAP_ACK;
}

void T1OSAuxiliarySurface::SwapBuffersAsync(
    SwapCompletionCallback completion_callback,
    PresentationCallback presentation_callback,
    gfx::FrameData data) {
  glFlush();
  if (completion_callback) {
    std::move(completion_callback)
        .Run(gfx::SwapCompletionResult(gfx::SwapResult::SWAP_ACK));
  }
  if (presentation_callback) {
    std::move(presentation_callback)
        .Run(gfx::PresentationFeedback(base::TimeTicks::Now(),
                                       base::Seconds(1) / 60,
                                       gfx::PresentationFeedback::kVSync));
  }
}

}  // namespace ui
