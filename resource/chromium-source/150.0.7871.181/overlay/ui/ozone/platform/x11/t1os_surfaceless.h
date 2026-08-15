// Copyright 2026 The One OS Authors
// Use of this source code is governed by a BSD-style license.

#ifndef UI_OZONE_PLATFORM_X11_T1OS_SURFACELESS_H_
#define UI_OZONE_PLATFORM_X11_T1OS_SURFACELESS_H_

#include <stdint.h>

#include <map>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include "base/files/file_descriptor_watcher_posix.h"
#include "base/files/scoped_file.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "base/task/sequenced_task_runner.h"
#include "base/threading/thread.h"
#include "ui/gfx/native_ui_types.h"
#include "ui/gl/gl_surface_egl.h"

struct gbm_bo;
struct gbm_surface;

namespace ui {

// A per-widget EGL/GBM window surface whose locked front buffers are exported
// to WindowServer as RGB DMA-BUFs. The render node and transport socket are
// both brokered into the GPU process; this class never discovers or opens a
// device path. Each successful Create() consumes one transport descriptor, so
// a second widget can never alias the first widget's EGLSurface or callbacks.
class T1OSGbmSurface final : public gl::GLSurfaceEGL {
 public:
  static scoped_refptr<T1OSGbmSurface> Create(
      gl::GLDisplayEGL* display,
      gfx::AcceleratedWidget owner_widget);

  T1OSGbmSurface(const T1OSGbmSurface&) = delete;
  T1OSGbmSurface& operator=(const T1OSGbmSurface&) = delete;

  bool Initialize(gl::GLSurfaceFormat format) override;
  void Destroy() override;
  bool IsOffscreen() override;
  bool SupportsAsyncSwap() override;
  bool Resize(const gfx::Size& size,
              float scale_factor,
              const gfx::ColorSpace& color_space,
              bool has_alpha) override;
  gfx::SwapResult SwapBuffers(PresentationCallback callback,
                              gfx::FrameData data) override;
  void SwapBuffersAsync(SwapCompletionCallback completion_callback,
                        PresentationCallback presentation_callback,
                        gfx::FrameData data) override;
  gfx::Size GetSize() override;
  void* GetHandle() override;

 protected:
  ~T1OSGbmSurface() override;

 private:
  using FrameKey = std::pair<uint64_t, uint64_t>;

  struct PendingFrame {
    raw_ptr<gbm_surface> owner_surface = nullptr;
    raw_ptr<gbm_bo> buffer = nullptr;
    SwapCompletionCallback completion_callback;
    PresentationCallback presentation_callback;
    bool presentation_received = false;
    bool presentation_succeeded = false;
  };

  struct RetiredGeneration {
    raw_ptr<gbm_surface> gbm = nullptr;
    EGLSurface egl = EGL_NO_SURFACE;
  };

  T1OSGbmSurface(gl::GLDisplayEGL* display,
                 gfx::AcceleratedWidget owner_widget,
                 base::ScopedFD socket);

  bool InitializeTransport();
  bool StartReadWatcher();
  bool ChooseGbmConfig();
  bool CreateGbmSurface(const gfx::Size& size);
  bool SendConfigure();
  bool SendFrame(uint64_t frame, gbm_bo* buffer);
  bool SendPacket(const std::string& packet,
                  const std::vector<int>& descriptors = {});
  gbm_bo* SwapAndExport(uint64_t frame);
  void OnReadable();
  void ProcessControlPacket(std::string packet);
  void OnTransportFailure(const char* reason);
  void CompleteFrame(uint64_t generation,
                     uint64_t frame,
                     bool presented,
                     bool dropped);
  void ReleaseBuffer(gbm_surface* owner_surface, gbm_bo* buffer);
  void ReleaseGeneration(uint64_t generation);
  void ReleaseAllFrames();
  bool RetireCurrentGeneration();
  void HandleCleared(uint64_t generation);
  void DrainRetiredGenerationsForDestroy();
  void DestroyRetiredGeneration(uint64_t generation);
  void DestroyGbmSurface();

  const gfx::AcceleratedWidget owner_widget_;
  base::ScopedFD socket_;
  scoped_refptr<base::SequencedTaskRunner> owning_task_runner_;
  base::Thread presentation_io_thread_{"T1OSPresentationIO"};
  std::unique_ptr<base::FileDescriptorWatcher> file_descriptor_watcher_;
  std::unique_ptr<base::FileDescriptorWatcher::Controller> read_watcher_;
  raw_ptr<gbm_surface> gbm_surface_ = nullptr;
  EGLSurface surface_ = EGL_NO_SURFACE;
  gfx::Size size_{1, 1};
  uint64_t generation_ = 0;
  uint64_t next_frame_ = 1;
  std::map<FrameKey, PendingFrame> pending_frames_;
  std::map<uint64_t, RetiredGeneration> retired_generations_;
  bool transport_initialized_ = false;
  bool failed_ = false;

  base::WeakPtr<T1OSGbmSurface> weak_this_;
  base::WeakPtrFactory<T1OSGbmSurface> weak_factory_{this};
};

// A same-display containment surface for an unexpected second top-level
// Chromium widget. T1OS presentation v1 intentionally authorizes one visible
// root; returning nullptr for another persistent root makes Viz repeatedly lose
// its output surface and can loop GPU-process restarts. This pbuffer accepts and
// completes swaps without presenting them, keeping the root GPU context alive
// while the launcher prevents multi-window session restore. Visible multi-root
// output requires a future multiplexed presentation protocol.
class T1OSAuxiliarySurface final : public gl::PbufferGLSurfaceEGL {
 public:
  static scoped_refptr<T1OSAuxiliarySurface> Create(
      gl::GLDisplayEGL* display,
      gfx::AcceleratedWidget owner_widget);

  T1OSAuxiliarySurface(const T1OSAuxiliarySurface&) = delete;
  T1OSAuxiliarySurface& operator=(const T1OSAuxiliarySurface&) = delete;

  bool IsOffscreen() override;
  bool SupportsAsyncSwap() override;
  gfx::SwapResult SwapBuffers(PresentationCallback callback,
                              gfx::FrameData data) override;
  void SwapBuffersAsync(SwapCompletionCallback completion_callback,
                        PresentationCallback presentation_callback,
                        gfx::FrameData data) override;

 protected:
  ~T1OSAuxiliarySurface() override;

 private:
  explicit T1OSAuxiliarySurface(gl::GLDisplayEGL* display);
};

}  // namespace ui

#endif  // UI_OZONE_PLATFORM_X11_T1OS_SURFACELESS_H_
