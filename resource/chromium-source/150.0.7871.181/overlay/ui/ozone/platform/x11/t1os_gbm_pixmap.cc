// Copyright 2026 The One OS Authors
// Use of this source code is governed by a BSD-style license.

#include "ui/ozone/platform/x11/t1os_gbm_pixmap.h"

#include <utility>

#include "base/check.h"

namespace ui {

T1OSGbmPixmap::T1OSGbmPixmap(std::unique_ptr<GbmBuffer> buffer)
    : buffer_(std::move(buffer)) {
  CHECK(buffer_);
}

T1OSGbmPixmap::~T1OSGbmPixmap() = default;

bool T1OSGbmPixmap::AreDmaBufFdsValid() const {
  return buffer_->AreFdsValid();
}

int T1OSGbmPixmap::GetDmaBufFd(size_t plane) const {
  return buffer_->GetPlaneFd(plane);
}

uint32_t T1OSGbmPixmap::GetDmaBufPitch(size_t plane) const {
  return buffer_->GetPlaneStride(plane);
}

size_t T1OSGbmPixmap::GetDmaBufOffset(size_t plane) const {
  return buffer_->GetPlaneOffset(plane);
}

size_t T1OSGbmPixmap::GetDmaBufPlaneSize(size_t plane) const {
  return buffer_->GetPlaneSize(plane);
}

uint64_t T1OSGbmPixmap::GetFormatModifier() const {
  return buffer_->GetFormatModifier();
}

viz::SharedImageFormat T1OSGbmPixmap::GetSharedImageFormat() const {
  return buffer_->GetSharedImageFormat();
}

size_t T1OSGbmPixmap::GetNumberOfPlanes() const {
  return buffer_->GetNumPlanes();
}

bool T1OSGbmPixmap::SupportsZeroCopyWebGPUImport() const {
  return buffer_->SupportsZeroCopyWebGPUImport();
}

gfx::Size T1OSGbmPixmap::GetBufferSize() const {
  return buffer_->GetSize();
}

uint32_t T1OSGbmPixmap::GetUniqueId() const {
  return buffer_->GetHandle();
}

bool T1OSGbmPixmap::ScheduleOverlayPlane(
    gfx::AcceleratedWidget widget,
    const gfx::OverlayPlaneData& overlay_plane_data,
    std::vector<gfx::GpuFence> acquire_fences,
    std::vector<gfx::GpuFence> release_fences) {
  // T1OS presents the composed root through T1OSSurfaceless rather than KMS.
  return false;
}

gfx::NativePixmapHandle T1OSGbmPixmap::ExportHandle() const {
  return buffer_->ExportHandle();
}

}  // namespace ui
