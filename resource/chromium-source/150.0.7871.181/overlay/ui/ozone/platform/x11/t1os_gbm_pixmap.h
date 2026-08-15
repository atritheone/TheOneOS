// Copyright 2026 The One OS Authors
// Use of this source code is governed by a BSD-style license.

#ifndef UI_OZONE_PLATFORM_X11_T1OS_GBM_PIXMAP_H_
#define UI_OZONE_PLATFORM_X11_T1OS_GBM_PIXMAP_H_

#include <memory>
#include <vector>

#include "ui/gfx/linux/gbm_buffer.h"
#include "ui/gfx/native_pixmap.h"

namespace ui {

// A NativePixmap that retains the GBM object which produced its DMA-BUFs.
// NVIDIA's GBM/EGL stack requires this lifetime to extend through EGLImage
// creation and use; retaining only duplicated plane descriptors is not enough
// on every driver release.
class T1OSGbmPixmap final : public gfx::NativePixmap {
 public:
  explicit T1OSGbmPixmap(std::unique_ptr<GbmBuffer> buffer);

  T1OSGbmPixmap(const T1OSGbmPixmap&) = delete;
  T1OSGbmPixmap& operator=(const T1OSGbmPixmap&) = delete;

  bool AreDmaBufFdsValid() const override;
  int GetDmaBufFd(size_t plane) const override;
  uint32_t GetDmaBufPitch(size_t plane) const override;
  size_t GetDmaBufOffset(size_t plane) const override;
  size_t GetDmaBufPlaneSize(size_t plane) const override;
  uint64_t GetFormatModifier() const override;
  viz::SharedImageFormat GetSharedImageFormat() const override;
  size_t GetNumberOfPlanes() const override;
  bool SupportsZeroCopyWebGPUImport() const override;
  gfx::Size GetBufferSize() const override;
  uint32_t GetUniqueId() const override;
  bool ScheduleOverlayPlane(
      gfx::AcceleratedWidget widget,
      const gfx::OverlayPlaneData& overlay_plane_data,
      std::vector<gfx::GpuFence> acquire_fences,
      std::vector<gfx::GpuFence> release_fences) override;
  gfx::NativePixmapHandle ExportHandle() const override;

 private:
  ~T1OSGbmPixmap() override;

  const std::unique_ptr<GbmBuffer> buffer_;
};

}  // namespace ui

#endif  // UI_OZONE_PLATFORM_X11_T1OS_GBM_PIXMAP_H_
