#!/usr/bin/env python3
"""Add the VirtualBox VMSVGA video decoder backend to a pinned Mesa tree."""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"{label} did not match the pinned Mesa source")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def function_source(source: str, name: str) -> str:
    name_at = source.index(name)
    line_at = source.rfind("\n", 0, name_at) + 1
    return_line = source.rfind("\n", 0, line_at - 1) + 1
    brace_at = source.index("{", name_at)
    depth = 0
    for position in range(brace_at, len(source)):
        if source[position] == "{":
            depth += 1
        elif source[position] == "}":
            depth -= 1
            if depth == 0:
                return source[return_line : position + 1]
    raise SystemExit(f"Could not extract Mesa function {name}")


if len(sys.argv) != 3:
    raise SystemExit("usage: apply_svga_video.py MESA_SOURCE PATCH_SOURCE")

mesa = Path(sys.argv[1]).resolve()
patch = Path(sys.argv[2]).resolve()
svga = mesa / "src/gallium/drivers/svga"
d3d12 = mesa / "src/gallium/drivers/d3d12"

for filename in (
    "svga_video.cpp",
    "svga_video_bridge.c",
    "svga_video.h",
    "svga_vbox_video.h",
):
    shutil.copy2(patch / filename, svga / filename)

# Reuse Mesa's tested Gallium-to-DXVA H.264 translation.  These two functions
# do not depend on D3D12 itself, but Mesa currently keeps them in that driver.
d3d_header = (d3d12 / "d3d12_video_dec_h264.h").read_text(encoding="utf-8")
struct_start = d3d_header.rfind(
    "#pragma pack(push", 0, d3d_header.index("typedef struct _DXVA_PicEntry_H264")
)
slice_at = d3d_header.index("typedef struct _DXVA_Slice_H264_Short")
struct_end = d3d_header.index("#pragma pack(pop, BeforeDXVApacking)", slice_at)
struct_end = d3d_header.index("\n", struct_end) + 1
dxva_structs = d3d_header[struct_start:struct_end]

generated_header = f"""/*
 * Generated at build time from Mesa's MIT-licensed D3D12 H.264 translator.
 */
#ifndef SVGA_VIDEO_DXVA_H264_H
#define SVGA_VIDEO_DXVA_H264_H

#include <cstdint>
#include "pipe/p_video_state.h"

constexpr uint16_t DXVA_H264_INVALID_PICTURE_INDEX = 0x7f;
constexpr uint16_t DXVA_H264_INVALID_PICTURE_ENTRY_VALUE = 0xff;

{dxva_structs}
DXVA_PicParams_H264
svga_dxva_picparams_from_pipe(uint32_t frame_num,
                              pipe_video_profile profile,
                              uint32_t frame_width,
                              uint32_t frame_height,
                              pipe_h264_picture_desc *picture);

void
svga_dxva_qmatrix_from_pipe(pipe_h264_picture_desc *picture,
                            DXVA_Qmatrix_H264 &matrix);

#endif
"""
(svga / "svga_video_dxva_h264.h").write_text(generated_header, encoding="utf-8")

d3d_source = (d3d12 / "d3d12_video_dec_h264.cpp").read_text(encoding="utf-8")
pic_name = "d3d12_video_decoder_dxva_picparams_from_pipe_picparams_h264"
matrix_name = "d3d12_video_decoder_dxva_qmatrix_from_pipe_picparams_h264"
pic_function = function_source(d3d_source, pic_name)
matrix_function = function_source(d3d_source, matrix_name)

generated_functions = "\n\n".join((pic_function, matrix_function))
generated_functions = generated_functions.replace(
    pic_name, "svga_dxva_picparams_from_pipe"
).replace(matrix_name, "svga_dxva_qmatrix_from_pipe")
generated_functions = generated_functions.replace(
    "D3D12_VIDEO_H264_MB_IN_PIXELS", "16"
)
generated_functions = re.sub(r"\buint\b", "unsigned", generated_functions)

generated_source = f"""/*
 * Generated at build time from Mesa's MIT-licensed D3D12 H.264 translator.
 */
#include <cassert>
#include <cmath>

#include "util/vl_zscan_data.h"
#include "svga_video_dxva_h264.h"

{generated_functions}
"""
(svga / "svga_video_dxva_h264.cpp").write_text(
    generated_source, encoding="utf-8"
)

replace_once(
    svga / "meson.build",
    """  'svga_cmd_vgpu10.c',
  'svga_context.c',""",
    """  'svga_cmd_vgpu10.c',
  'svga_context.c',
  'svga_video.cpp',
  'svga_video_bridge.c',
  'svga_video_dxva_h264.cpp',""",
    "Mesa SVGA source list",
)
replace_once(
    svga / "meson.build",
    """  c_args : [c_msvc_compat_args],
  gnu_symbol_visibility : 'hidden',""",
    """  c_args : [c_msvc_compat_args],
  cpp_args : [cpp_msvc_compat_args],
  gnu_symbol_visibility : 'hidden',""",
    "Mesa SVGA C++ arguments",
)
replace_once(
    svga / "svga_context.c",
    """#include "svga_streamout.h"

#define CONST0_UPLOAD_DEFAULT_SIZE 65536""",
    """#include "svga_streamout.h"
#include "svga_video.h"

#define CONST0_UPLOAD_DEFAULT_SIZE 65536""",
    "Mesa SVGA context includes",
)
replace_once(
    svga / "svga_context.c",
    """   svga_init_resource_functions(svga);
   svga_init_blend_functions(svga);""",
    """   svga_init_resource_functions(svga);
   svga->pipe.create_video_codec = svga_video_create_codec;
   svga->pipe.create_video_buffer = svga_video_create_buffer;
   svga_init_blend_functions(svga);""",
    "Mesa SVGA video context hooks",
)
# Insert includes using a separate exact anchor because include order has varied
# less than the body across the pinned Mesa releases.
screen = svga / "svga_screen.c"
screen_text = screen.read_text(encoding="utf-8")
screen_anchor = '#include "svga_screen.h"\n'
if screen_text.count(screen_anchor) != 1:
    raise SystemExit("Mesa SVGA screen header anchor did not match")
screen_text = screen_text.replace(
    screen_anchor,
    screen_anchor + '#include "svga_video.h"\n#include "vl/vl_video_buffer.h"\n',
    1,
)
screen.write_text(screen_text, encoding="utf-8")

replace_once(
    screen,
    """   screen->is_format_supported = svga_is_format_supported;
   screen->context_create = svga_context_create;""",
    """   screen->is_format_supported = svga_is_format_supported;
   screen->get_video_param = svga_video_get_param;
   screen->is_video_format_supported = svga_video_is_format_supported;
   screen->context_create = svga_context_create;""",
    "Mesa SVGA video screen hooks",
)
replace_once(
    svga / "svga_resource_texture.c",
    """   tex->key.flags = 0;
   tex->key.size.width = template->width0;""",
    """   tex->key.flags = 0;
   if ((template->bind & PIPE_BIND_CUSTOM) &&
       template->format == PIPE_FORMAT_NV12)
      tex->key.flags |= SVGA3D_SURFACE_RESERVED1;
   tex->key.size.width = template->width0;""",
    "Mesa SVGA decoder render-target surface flag",
)
replace_once(
    svga / "svga_format.c",
    """{
   const struct vgpu10_format_entry *entry = svga_format_entry(format);

   if (ss->sws->have_vgpu10) {""",
    """{
   if ((bind & PIPE_BIND_CUSTOM) && format == PIPE_FORMAT_NV12)
      return SVGA3D_NV12;

   const struct vgpu10_format_entry *entry = svga_format_entry(format);

   if (ss->sws->have_vgpu10) {""",
    "Mesa SVGA NV12 decoder surface format",
)
replace_once(
    mesa / "src/gallium/winsys/svga/drm/vmw_screen_dri.c",
    """    whandle->stride = stride;
    whandle->offset = 0;
    whandle->modifier = DRM_FORMAT_MOD_LINEAR;""",
    """    whandle->stride = stride;
    whandle->offset = 0;
    whandle->size = vsrf->size;
    whandle->modifier = DRM_FORMAT_MOD_LINEAR;""",
    "Mesa SVGA exported surface size",
)
replace_once(
    mesa / "src/gallium/frontends/va/surface.c",
    """   desc->height = surf->templat.height;
   desc->num_objects = 0;

   bool supports_contiguous_planes = screen->resource_get_param && surf->buffer->contiguous_planes;""",
    """   desc->height = surf->templat.height;
   desc->num_objects = 0;

   /*
    * T1OS's VMSVGA decoder uses one host NV12 surface for both planes.
    * Gallium exposes two plane views of that same resource, so the generic
    * exporter would incorrectly create two objects with both offsets at zero.
    * Export the packed surface once and describe its Y and interleaved UV
    * planes explicitly.
    */
   if ((flags & VA_EXPORT_SURFACE_COMPOSED_LAYERS) &&
       surf->buffer->buffer_format == PIPE_FORMAT_NV12 &&
       surfaces[0].texture &&
       surfaces[1].texture == surfaces[0].texture) {
      struct winsys_handle whandle;
      struct pipe_resource *resource = surfaces[0].texture;
      uint32_t pitch;
      uint32_t uv_offset;
      uint32_t minimum_size;

      memset(&whandle, 0, sizeof(whandle));
      whandle.type = WINSYS_HANDLE_TYPE_FD;
      if (!screen->resource_get_handle(screen, drv->pipe, resource,
                                       &whandle, usage)) {
         fprintf(stderr,
                 "Mesa VA export: packed NV12 resource export failed "
                 "surface=%u\\n", surface_id);
         mtx_unlock(&drv->mutex);
         return VA_STATUS_ERROR_INVALID_SURFACE;
      }

      pitch = whandle.stride ? whandle.stride : resource->width0;
      uv_offset = pitch * resource->height0;
      minimum_size = uv_offset + pitch * DIV_ROUND_UP(resource->height0, 2);

      desc->num_objects = 1;
      desc->objects[0].fd = (int)whandle.handle;
      desc->objects[0].size =
         whandle.size >= minimum_size ? (uint32_t)whandle.size : minimum_size;
      desc->objects[0].drm_format_modifier = whandle.modifier;
      desc->num_layers = 1;
      desc->layers[0].drm_format = DRM_FORMAT_NV12;
      desc->layers[0].num_planes = 2;
      desc->layers[0].object_index[0] = 0;
      desc->layers[0].object_index[1] = 0;
      desc->layers[0].offset[0] = whandle.offset;
      desc->layers[0].offset[1] = whandle.offset + uv_offset;
      desc->layers[0].pitch[0] = pitch;
      desc->layers[0].pitch[1] = pitch;

      drv->has_external_handles = true;
      mtx_unlock(&drv->mutex);
      return VA_STATUS_SUCCESS;
   }

   bool supports_contiguous_planes = screen->resource_get_param && surf->buffer->contiguous_planes;""",
    "Mesa VA packed NV12 DMA-BUF export",
)
replace_once(
    mesa / "src/gallium/winsys/svga/drm/vmw_screen_dri.c",
    """    int ret;

    if (whandle->offset != 0) {
       fprintf(stderr, "Attempt to import unsupported winsys offset %u\\n",
               whandle->offset);
       return NULL;
    }

    ret = vmw_ioctl_gb_surface_ref(vws, whandle, &flags, format,
                                   &mip_levels, &handle, &desc.region);

    if (ret) {
        fprintf(stderr, "Failed referencing shared surface. SID %d.\\n"
                "Error %d (%s).\\n",
                whandle->handle, ret, strerror(-ret));
        return NULL;
    }
""",
    """    int ret;

    ret = vmw_ioctl_gb_surface_ref(vws, whandle, &flags, format,
                                   &mip_levels, &handle, &desc.region);

    if (ret) {
        fprintf(stderr, "Failed referencing shared surface. SID %d.\\n"
                "Error %d (%s).\\n",
                whandle->handle, ret, strerror(-ret));
        return NULL;
    }

    /*
     * A shared SVGA NV12 surface owns its plane layout.  EGL supplies the
     * physical UV byte offset, but both plane views must reference the same
     * host surface and select the plane through their view format.
     */
    if (whandle->offset != 0 && *format != SVGA3D_NV12) {
       fprintf(stderr, "Attempt to import unsupported winsys offset %u\\n",
               whandle->offset);
       goto out_mip;
    }
""",
    "Mesa SVGA GB NV12 plane-offset import",
)
replace_once(
    mesa / "src/gallium/winsys/svga/drm/vmw_screen_dri.c",
    """    int ret;
    int i;

    if (whandle->offset != 0) {
       fprintf(stderr, "Attempt to import unsupported winsys offset %u\\n",
               whandle->offset);
       return NULL;
    }

    switch (whandle->type) {""",
    """    int ret;
    int i;

    switch (whandle->type) {""",
    "Mesa SVGA legacy deferred plane-offset validation",
)
replace_once(
    mesa / "src/gallium/winsys/svga/drm/vmw_screen_dri.c",
    """    if (ret) {
       /*
        * Any attempt to share something other than a surface, like a dumb
        * kms buffer, should fail here.
        */
       vmw_error("Failed referencing shared surface. SID %d.\\n"
                 "Error %d (%s).\\n",
                 handle, ret, strerror(-ret));
       return NULL;
    }

    if (rep->mip_levels[0] != 1) {""",
    """    if (ret) {
       /*
        * Any attempt to share something other than a surface, like a dumb
        * kms buffer, should fail here.
        */
       vmw_error("Failed referencing shared surface. SID %d.\\n"
                 "Error %d (%s).\\n",
                 handle, ret, strerror(-ret));
       return NULL;
    }

    if (whandle->offset != 0 && rep->format != SVGA3D_NV12) {
       fprintf(stderr, "Attempt to import unsupported winsys offset %u\\n",
               whandle->offset);
       goto out_mip;
    }

    if (rep->mip_levels[0] != 1) {""",
    "Mesa SVGA legacy NV12 plane-offset import",
)
replace_once(
    svga / "svga_format.c",
    """{
   SVGA3dSurfaceFormat default_format =
      svga_translate_format(ss, pformat, bind);""",
    """{
   if (sformat == SVGA3D_NV12 &&
       (pformat == PIPE_FORMAT_NV12 ||
        pformat == PIPE_FORMAT_R8_UNORM ||
        pformat == PIPE_FORMAT_R8G8_UNORM))
      return true;

   SVGA3dSurfaceFormat default_format =
      svga_translate_format(ss, pformat, bind);""",
    "Mesa SVGA shared NV12 plane-view formats",
)
