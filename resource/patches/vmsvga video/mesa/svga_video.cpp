/*
 * SPDX-License-Identifier: MIT
 *
 * Gallium H.264 bitstream decoding over the VirtualBox VMSVGA DX video ABI.
 */

#include <algorithm>
#include <climits>
#include <cstddef>
#include <cstdio>
#include <cstring>
#include <vector>

#include "pipe/p_context.h"
#include "pipe/p_screen.h"
#include "pipe/p_state.h"
#include "pipe/p_video_state.h"
#include "util/u_inlines.h"
#include "util/u_math.h"
#include "util/u_memory.h"
#include "util/os_time.h"
#include "util/u_sampler.h"
#include "util/u_video.h"
#include "vl/vl_defines.h"
#include "svga_context.h"
#include "svga_screen.h"
#include "svga_video.h"
#include "svga_vbox_video.h"

#include "svga_video_dxva_h264.h"

extern "C" void *
SVGA3D_FIFOReserve(struct svga_winsys_context *swc,
                   uint32_t command, uint32_t size, uint32_t relocations);

extern "C" struct pipe_video_buffer *
vl_video_buffer_create(struct pipe_context *pipe,
                       const struct pipe_video_buffer *templ);

extern "C" struct svga_winsys_buffer *
svga_winsys_buffer_create(struct svga_context *svga,
                          unsigned alignment,
                          unsigned usage,
                          unsigned size);

extern "C" void
vl_video_buffer_set_associated_data(struct pipe_video_buffer *buffer,
                                    struct pipe_video_codec *codec,
                                    void *data,
                                    void (*destroy_data)(void *));

extern "C" void *
vl_video_buffer_get_associated_data(struct pipe_video_buffer *buffer,
                                    struct pipe_video_codec *codec);

struct svga_video_buffer_data {
   struct svga_context *svga;
   struct svga_winsys_surface *surface;
   uint32_t view_id;
   VBSVGA3dGuid profile;
   bool defined;
};

struct svga_video_buffer {
   struct pipe_video_buffer base;
   struct pipe_resource *resource;
   struct pipe_sampler_view *planes[VL_NUM_COMPONENTS];
   struct pipe_sampler_view *components[VL_NUM_COMPONENTS];
   struct pipe_surface surfaces[VL_NUM_COMPONENTS];
};

struct svga_video_codec {
   struct pipe_video_codec base;
   struct svga_context *svga;
   uint32_t decoder_id;
   uint32_t next_view_id;
   uint32_t feedback;
   VBSVGA3dGuid profile;
   static constexpr unsigned argument_slot_count = 8;
   struct pipe_resource *arguments[argument_slot_count][4];
   struct pipe_fence_handle *argument_fences[argument_slot_count];
   unsigned argument_slot;
   unsigned next_argument_slot;
};

static const VBSVGA3dGuid dxva_h264_vld_no_fgt = {
   0x1b81be68, 0xa0c7, 0x11d3, {0xb9, 0x84, 0x00, 0xc0, 0x4f, 0x2e, 0x73, 0xc5}
};

static constexpr uint64_t vbox_video_query_timeout_ns =
   2ull * 1000ull * 1000ull * 1000ull;

static_assert(sizeof(VBSVGA3dVideoDecoderDesc) == 28);
static_assert(sizeof(VBSVGA3dVideoDecoderConfig) == 100);
static_assert(sizeof(VBSVGA3dDecodeProfileInfo) == 19);
static_assert(sizeof(VBSVGA3dCmdDXGetVideoCapability) == 24);
static_assert(offsetof(VBSVGA3dVideoCapabilityMobLayout, data) == 12);

static bool
guid_equal(const VBSVGA3dGuid &a, const VBSVGA3dGuid &b)
{
   return std::memcmp(&a, &b, sizeof(a)) == 0;
}

static bool
svga_has_vbox_video(struct pipe_screen *screen)
{
   struct svga_screen *ss = svga_screen(screen);
   SVGA3dDevCapResult cap = {};

   /*
    * VirtualBox 7.2 builds the guest-visible SVGA devcap table before its
    * D3D11 video device is attached.  The host log can therefore report a
    * working VideoDevice and hardware decode profiles while DEVCAP_3D retains
    * only VBSVGA3D_CAP_3D.  This backend is installed only with T1OS's
    * VirtualBox-specific vmwgfx command verifier, so VGPU10 plus the
    * VirtualBox 3D bit is the reliable capability gate.  The GET_VIDEO_CAPABILITY
    * command remains the authoritative per-codec check in create_codec().
    */
   return ss->sws->have_vgpu10 &&
          ss->sws->get_cap(ss->sws, SVGA3D_DEVCAP_3D, &cap) &&
          (cap.u & VBSVGA3D_CAP_3D) != 0;
}

static bool
svga_vbox_video_decoder_config(
   struct pipe_context *context,
   const VBSVGA3dVideoDecoderDesc &desc,
   VBSVGA3dVideoDecoderConfig *selected)
{
   /*
    * Match VirtualBox's WDDM guest implementation: a normal 64 KiB MOB,
    * mapped only before submission and after the command-stream fence.  The
    * pinned query pool is intentionally avoided here.  vmwgfx strips
    * DONTBLOCK when UNSYNCHRONIZED is set, so polling a busy pinned buffer
    * can otherwise turn a bounded capability check into an unbounded map.
    */
   constexpr uint32_t capability_size = 64 * 1024;
   std::fprintf(
      stderr,
      "T1OS VMSVGA video: requesting decoder config %ux%u format=%u\n",
      desc.SampleWidth,
      desc.SampleHeight,
      static_cast<unsigned>(desc.OutputFormat));
   auto *svga = svga_context(context);
   auto *screen = context->screen;
   auto *sws = svga_screen(screen)->sws;
   auto *buffer = svga_winsys_buffer_create(svga, 4096, 0, capability_size);
   if (!buffer) {
      std::fprintf(
         stderr, "T1OS VMSVGA video: config capability MOB allocation failed\n");
      return false;
   }
   std::fprintf(stderr, "T1OS VMSVGA video: config capability MOB allocated\n");

   auto *layout = static_cast<VBSVGA3dVideoCapabilityMobLayout *>(
      sws->buffer_map(sws, buffer, PIPE_MAP_WRITE));
   if (!layout) {
      std::fprintf(
         stderr, "T1OS VMSVGA video: config capability MOB write map failed\n");
      sws->buffer_destroy(sws, buffer);
      return false;
   }
   std::memset(layout, 0, capability_size);
   layout->data.config.desc = desc;
   sws->buffer_unmap(sws, buffer);
   std::fprintf(stderr, "T1OS VMSVGA video: config descriptor staged\n");

   auto *cmd = static_cast<VBSVGA3dCmdDXGetVideoCapability *>(
      SVGA3D_FIFOReserve(svga->swc,
                         VBSVGA_3D_CMD_DX_GET_VIDEO_CAPABILITY,
                         sizeof(VBSVGA3dCmdDXGetVideoCapability), 2));
   if (!cmd) {
      std::fprintf(
         stderr, "T1OS VMSVGA video: config command reservation failed\n");
      sws->buffer_destroy(sws, buffer);
      return false;
   }

   std::memset(cmd, 0, sizeof(*cmd));
   cmd->capability = VBSVGA3D_VIDEO_CAPABILITY_DECODE_CONFIG;
   cmd->sizeInBytes = capability_size;
   cmd->fenceValue = 2;
   svga->swc->mob_relocation(
      svga->swc,
      &cmd->mobid,
      &cmd->offsetInBytes,
      buffer,
      0,
      SVGA_RELOC_READ | SVGA_RELOC_WRITE);
   svga->swc->commit(svga->swc);
   std::fprintf(stderr, "T1OS VMSVGA video: config command committed\n");

   struct pipe_fence_handle *fence = nullptr;
   context->flush(context, &fence, 0);
   std::fprintf(stderr, "T1OS VMSVGA video: config command flushed\n");
   bool completed =
      fence &&
      screen->fence_finish(
         screen, context, fence, vbox_video_query_timeout_ns);
   screen->fence_reference(screen, &fence, nullptr);
   if (!completed) {
      std::fprintf(
         stderr, "T1OS VMSVGA video: config command fence timed out\n");
      sws->buffer_destroy(sws, buffer);
      return false;
   }
   std::fprintf(stderr, "T1OS VMSVGA video: config command fence completed\n");

   layout = static_cast<VBSVGA3dVideoCapabilityMobLayout *>(
      sws->buffer_map(sws, buffer, PIPE_MAP_READ));
   if (!layout) {
      std::fprintf(
         stderr, "T1OS VMSVGA video: config capability MOB read map failed\n");
      sws->buffer_destroy(sws, buffer);
      return false;
   }

   bool found = false;
   const uint32_t header_size =
      offsetof(VBSVGA3dVideoCapabilityMobLayout, data);
   const uint32_t config_header_size =
      offsetof(VBSVGA3dDecodeConfigInfo, aConfig);
   std::fprintf(
      stderr,
      "T1OS VMSVGA video: decoder config response fence=%llu bytes=%u\n",
      static_cast<unsigned long long>(layout->fenceValue),
      layout->cbDataOut);
   if (layout->fenceValue == 2 &&
       layout->cbDataOut <= capability_size - header_size &&
       layout->cbDataOut >= config_header_size &&
       (layout->cbDataOut - config_header_size) %
          sizeof(VBSVGA3dVideoDecoderConfig) == 0 &&
       std::memcmp(&layout->data.config.desc, &desc, sizeof(desc)) == 0) {
      const uint32_t count =
         (layout->cbDataOut - config_header_size) /
         sizeof(VBSVGA3dVideoDecoderConfig);
      for (uint32_t index = 0; index < count; ++index) {
         const auto &candidate = layout->data.config.aConfig[index];
         std::fprintf(
            stderr,
            "T1OS VMSVGA video: config[%u] raw=%u targets=%u\n",
            index,
            candidate.ConfigBitstreamRaw,
            candidate.ConfigMinRenderTargetBuffCount);
         /*
          * Gallium supplies an H.264 elementary bitstream plus short slice
          * control records. DXVA identifies that contract as raw mode 2.
          */
         if (candidate.ConfigBitstreamRaw == 2) {
            *selected = candidate;
            found = true;
            break;
         }
      }
   }

   std::fprintf(stderr,
                "T1OS VMSVGA video: config response parsed found=%u\n",
                found ? 1u : 0u);
   sws->buffer_unmap(sws, buffer);
   std::fprintf(stderr,
                "T1OS VMSVGA video: config capability MOB unmapped\n");
   sws->buffer_destroy(sws, buffer);
   std::fprintf(stderr,
                "T1OS VMSVGA video: config capability MOB destroyed\n");
   std::fprintf(
      stderr,
      "T1OS VMSVGA video: decoder config %s\n",
      found ? "selected raw mode 2" : "missing raw mode 2");
   return found;
}

extern "C" int
svga_video_get_param(struct pipe_screen *screen,
                     enum pipe_video_profile profile,
                     enum pipe_video_entrypoint entrypoint,
                     enum pipe_video_cap param)
{
   const bool h264 = u_reduce_video_profile(profile) == PIPE_VIDEO_FORMAT_MPEG4_AVC;
   const bool supported = svga_has_vbox_video(screen) && h264 &&
                          entrypoint == PIPE_VIDEO_ENTRYPOINT_BITSTREAM;

   switch (param) {
   case PIPE_VIDEO_CAP_SUPPORTED:
      return supported;
   case PIPE_VIDEO_CAP_NPOT_TEXTURES:
      return 1;
   case PIPE_VIDEO_CAP_MAX_WIDTH:
   case PIPE_VIDEO_CAP_MAX_HEIGHT:
      return supported ? 4096 : 0;
   case PIPE_VIDEO_CAP_MIN_WIDTH:
   case PIPE_VIDEO_CAP_MIN_HEIGHT:
      return supported ? 16 : 0;
   case PIPE_VIDEO_CAP_PREFERRED_FORMAT:
      return PIPE_FORMAT_NV12;
   case PIPE_VIDEO_CAP_SUPPORTS_PROGRESSIVE:
      return supported;
   case PIPE_VIDEO_CAP_MAX_LEVEL:
      return supported ? 52 : 0;
   case PIPE_VIDEO_CAP_MAX_MACROBLOCKS:
      return supported ? 65536 : 0;
   case PIPE_VIDEO_CAP_SKIP_CLEAR_SURFACE:
      /*
       * The VA frontend asks this with UNKNOWN profile/entrypoint while
       * allocating its pool.  DXVA overwrites the complete output target,
       * and trying to clear the packed NV12 resource through the ordinary
       * render-target path is both unnecessary and unsupported.
       */
      return svga_has_vbox_video(screen);
   case PIPE_VIDEO_CAP_SUPPORTS_CONTIGUOUS_PLANES_MAP:
      return 0;
   default:
      return 0;
   }
}

extern "C" bool
svga_video_is_format_supported(struct pipe_screen *screen,
                               enum pipe_format format,
                               enum pipe_video_profile profile,
                               enum pipe_video_entrypoint entrypoint)
{
   /*
    * The VirtualBox DXVA output view is an NV12 surface.  Advertising IYUV
    * or YV12 makes libavcodec choose a software-planar match for H.264 and
    * bypasses the host-decoder surface implementation.
    */
   return svga_has_vbox_video(screen) &&
          format == PIPE_FORMAT_NV12 &&
          (profile == PIPE_VIDEO_PROFILE_UNKNOWN ||
           u_reduce_video_profile(profile) == PIPE_VIDEO_FORMAT_MPEG4_AVC) &&
          entrypoint == PIPE_VIDEO_ENTRYPOINT_BITSTREAM;
}

static void
emit_destroy_view(void *opaque)
{
   auto *data = static_cast<svga_video_buffer_data *>(opaque);
   if (data && data->defined && data->svga && data->svga->swc) {
      auto *cmd = static_cast<VBSVGA3dCmdDXDestroyVideoDecoderOutputView *>(
         SVGA3D_FIFOReserve(data->svga->swc,
                            VBSVGA_3D_CMD_DX_DESTROY_VIDEO_DECODER_OUTPUT_VIEW,
                            sizeof(VBSVGA3dCmdDXDestroyVideoDecoderOutputView), 0));
      if (cmd) {
         cmd->videoDecoderOutputViewId = data->view_id;
         data->svga->swc->commit(data->svga->swc);
      }
   }
   FREE(data);
}

static void
svga_video_buffer_destroy(struct pipe_video_buffer *base)
{
   auto *buffer = reinterpret_cast<svga_video_buffer *>(base);
   struct pipe_context *pipe = base->context;

   for (auto *&view : buffer->planes)
      pipe->sampler_view_release(pipe, view);
   for (auto *&view : buffer->components)
      pipe->sampler_view_release(pipe, view);
   if (base->associated_data && base->destroy_associated_data)
      base->destroy_associated_data(base->associated_data);
   pipe_resource_reference(&buffer->resource, nullptr);
   FREE(buffer);
}

static void
svga_video_buffer_resources(struct pipe_video_buffer *base,
                            struct pipe_resource **resources)
{
   auto *buffer = reinterpret_cast<svga_video_buffer *>(base);
   resources[0] = buffer->resource;
}

static struct pipe_sampler_view *
create_plane_view(struct svga_video_buffer *buffer,
                  enum pipe_format format, unsigned swizzle)
{
   struct pipe_sampler_view templ = {};
   u_sampler_view_default_template(&templ, buffer->resource, format);
   templ.swizzle_r = templ.swizzle_g = templ.swizzle_b = swizzle;
   templ.swizzle_a = PIPE_SWIZZLE_1;
   return buffer->base.context->create_sampler_view(
      buffer->base.context, buffer->resource, &templ);
}

static struct pipe_sampler_view **
svga_video_buffer_plane_views(struct pipe_video_buffer *base)
{
   auto *buffer = reinterpret_cast<svga_video_buffer *>(base);
   if (!buffer->planes[0])
      buffer->planes[0] =
         create_plane_view(buffer, PIPE_FORMAT_R8_UNORM, PIPE_SWIZZLE_X);
   if (!buffer->planes[1])
      buffer->planes[1] =
         create_plane_view(buffer, PIPE_FORMAT_R8G8_UNORM, PIPE_SWIZZLE_X);
   if (!buffer->planes[0] || !buffer->planes[1])
      return nullptr;
   return buffer->planes;
}

static struct pipe_sampler_view **
svga_video_buffer_component_views(struct pipe_video_buffer *base)
{
   auto *buffer = reinterpret_cast<svga_video_buffer *>(base);
   if (!buffer->components[0])
      buffer->components[0] =
         create_plane_view(buffer, PIPE_FORMAT_R8_UNORM, PIPE_SWIZZLE_X);
   if (!buffer->components[1])
      buffer->components[1] =
         create_plane_view(buffer, PIPE_FORMAT_R8G8_UNORM, PIPE_SWIZZLE_X);
   if (!buffer->components[2])
      buffer->components[2] =
         create_plane_view(buffer, PIPE_FORMAT_R8G8_UNORM, PIPE_SWIZZLE_Y);
   if (!buffer->components[0] || !buffer->components[1] ||
       !buffer->components[2])
      return nullptr;
   return buffer->components;
}

static struct pipe_surface *
svga_video_buffer_surfaces(struct pipe_video_buffer *base)
{
   auto *buffer = reinterpret_cast<svga_video_buffer *>(base);
   return buffer->surfaces;
}

extern "C" struct pipe_video_buffer *
svga_video_create_buffer(struct pipe_context *context,
                         const struct pipe_video_buffer *templ)
{
   if (templ->buffer_format != PIPE_FORMAT_NV12)
      return vl_video_buffer_create(context, templ);

   struct pipe_resource resource_templ = {};

   resource_templ.target = PIPE_TEXTURE_2D;
   resource_templ.format = PIPE_FORMAT_NV12;
   resource_templ.width0 = align(templ->width, 16);
   resource_templ.height0 = align(templ->height, 16);
   resource_templ.depth0 = 1;
   resource_templ.array_size = 1;
   resource_templ.bind = PIPE_BIND_SAMPLER_VIEW | PIPE_BIND_CUSTOM;
   resource_templ.usage = PIPE_USAGE_DEFAULT;
   std::fprintf(stderr,
                "T1OS VMSVGA video: allocating NV12 surface %ux%u\n",
                resource_templ.width0,
                resource_templ.height0);
   struct pipe_resource *resource =
      context->screen->resource_create(context->screen, &resource_templ);
   if (!resource) {
      std::fprintf(stderr,
                   "T1OS VMSVGA video: NV12 surface allocation failed\n");
      return nullptr;
   }
   std::fprintf(stderr,
                "T1OS VMSVGA video: NV12 surface allocation complete\n");

   auto *buffer = CALLOC_STRUCT(svga_video_buffer);
   if (!buffer) {
      pipe_resource_reference(&resource, nullptr);
      return nullptr;
   }
   buffer->base = *templ;
   buffer->base.context = context;
   buffer->base.buffer_format = PIPE_FORMAT_NV12;
   /*
    * VirtualBox exposes decoder output as one packed NV12 texture even when
    * VA advertises interlaced decode support.  Gallium's generic interlaced
    * flag means separate field resources, which this buffer intentionally
    * does not use and which would make VA reject DMA-BUF export.
    */
   buffer->base.interlaced = false;
   buffer->base.width = resource_templ.width0;
   buffer->base.height = resource_templ.height0;
   buffer->base.contiguous_planes = false;
   buffer->base.destroy = svga_video_buffer_destroy;
   buffer->base.get_resources = svga_video_buffer_resources;
   buffer->base.get_sampler_view_planes = svga_video_buffer_plane_views;
   buffer->base.get_sampler_view_components =
      svga_video_buffer_component_views;
   buffer->base.get_surfaces = svga_video_buffer_surfaces;
   buffer->resource = resource;
   buffer->surfaces[0].texture = resource;
   buffer->surfaces[0].format = PIPE_FORMAT_R8_UNORM;
   buffer->surfaces[1].texture = resource;
   buffer->surfaces[1].format = PIPE_FORMAT_R8G8_UNORM;

   auto *data = CALLOC_STRUCT(svga_video_buffer_data);
   if (!data) {
      buffer->base.destroy(&buffer->base);
      return nullptr;
   }
   data->svga = svga_context(context);
   data->surface = svga_video_texture_handle(resource);
   data->view_id = SVGA3D_INVALID_ID;
   std::fprintf(stderr,
                "T1OS VMSVGA video: NV12 surface handle %s\n",
                data->surface ? "ready" : "missing");
   vl_video_buffer_set_associated_data(
      &buffer->base, nullptr, data, emit_destroy_view);
   return &buffer->base;
}

static svga_video_buffer_data *
buffer_data(struct pipe_video_buffer *buffer)
{
   if (!buffer)
      return nullptr;
   return static_cast<svga_video_buffer_data *>(
      vl_video_buffer_get_associated_data(buffer, nullptr));
}

static bool
ensure_output_view(svga_video_codec *codec, struct pipe_video_buffer *target)
{
   auto *data = buffer_data(target);
   if (!data || !data->surface)
      return false;
   if (data->defined) {
      if (!guid_equal(data->profile, codec->profile))
         return false;
      return true;
   }
   if (codec->next_view_id >= 127)
      return false;

   auto *cmd = static_cast<VBSVGA3dCmdDXDefineVideoDecoderOutputView *>(
      SVGA3D_FIFOReserve(codec->svga->swc,
                         VBSVGA_3D_CMD_DX_DEFINE_VIDEO_DECODER_OUTPUT_VIEW,
                         sizeof(VBSVGA3dCmdDXDefineVideoDecoderOutputView), 1));
   if (!cmd)
      return false;
   std::memset(cmd, 0, sizeof(*cmd));
   data->view_id = codec->next_view_id++;
   data->profile = codec->profile;
   cmd->videoDecoderOutputViewId = data->view_id;
   cmd->desc.DecodeProfile = codec->profile;
   cmd->desc.ViewDimension = VBSVGA3D_VDOV_DIMENSION_TEXTURE2D;
   codec->svga->swc->surface_relocation(codec->svga->swc, &cmd->sid, nullptr,
                                        data->surface, SVGA_RELOC_WRITE);
   codec->svga->swc->commit(codec->svga->swc);
   data->defined = true;
   return true;
}

static bool
upload_argument(svga_video_codec *codec, unsigned index,
                const void *data, unsigned size)
{
   if (!size)
      return false;
   struct pipe_resource *&resource =
      codec->arguments[codec->argument_slot][index];
   if (!resource || resource->width0 < size) {
      pipe_resource_reference(&resource, nullptr);
      resource = pipe_buffer_create(codec->base.context->screen,
                                    PIPE_BIND_CUSTOM, PIPE_USAGE_STREAM, size);
      if (!resource)
         return false;
   }
   pipe_buffer_write(codec->base.context, resource, 0, size, data);
   return true;
}

static struct svga_winsys_surface *
argument_surface(svga_video_codec *codec, unsigned index)
{
   return svga_video_argument_handle(
      codec->svga, codec->arguments[codec->argument_slot][index]);
}

static void
decoder_begin_frame(struct pipe_video_codec *base,
                    struct pipe_video_buffer *target,
                    struct pipe_picture_desc *)
{
   auto *codec = reinterpret_cast<svga_video_codec *>(base);
   codec->argument_slot = codec->next_argument_slot;
   codec->next_argument_slot =
      (codec->next_argument_slot + 1) %
      svga_video_codec::argument_slot_count;

   struct pipe_screen *screen = base->context->screen;
   struct pipe_fence_handle *&fence =
      codec->argument_fences[codec->argument_slot];
   if (fence) {
      if (!screen->fence_finish(
             screen, base->context, fence, OS_TIMEOUT_INFINITE))
         return;
      screen->fence_reference(screen, &fence, nullptr);
   }

   if (!ensure_output_view(codec, target))
      return;
   auto *data = buffer_data(target);
   auto *cmd = static_cast<VBSVGA3dCmdDXVideoDecoderBeginFrame *>(
      SVGA3D_FIFOReserve(codec->svga->swc,
                         VBSVGA_3D_CMD_DX_VIDEO_DECODER_BEGIN_FRAME,
                         sizeof(VBSVGA3dCmdDXVideoDecoderBeginFrame), 0));
   if (!cmd)
      return;
   cmd->videoDecoderId = codec->decoder_id;
   cmd->videoDecoderOutputViewId = data->view_id;
   codec->svga->swc->commit(codec->svga->swc);
}

static std::vector<uint8_t>
join_bitstream(unsigned count, const void *const *buffers, const unsigned *sizes)
{
   size_t total = 0;
   for (unsigned i = 0; i < count; ++i)
      total += sizes[i];
   std::vector<uint8_t> output;
   output.reserve(total);
   for (unsigned i = 0; i < count; ++i) {
      const auto *bytes = static_cast<const uint8_t *>(buffers[i]);
      output.insert(output.end(), bytes, bytes + sizes[i]);
   }
   return output;
}

static std::vector<DXVA_Slice_H264_Short>
make_slice_control(const struct pipe_h264_picture_desc *picture)
{
   std::vector<DXVA_Slice_H264_Short> slices(picture->slice_count);
   uint32_t offset = picture->slice_count ?
      picture->slice_parameter.slice_data_offset[0] : 0;
   for (uint32_t i = 0; i < picture->slice_count; ++i) {
      auto &slice = slices[i];
      switch (picture->slice_parameter.slice_data_flag[i]) {
      case PIPE_SLICE_BUFFER_PLACEMENT_TYPE_WHOLE:  slice.wBadSliceChopping = 0; break;
      case PIPE_SLICE_BUFFER_PLACEMENT_TYPE_BEGIN:  slice.wBadSliceChopping = 1; break;
      case PIPE_SLICE_BUFFER_PLACEMENT_TYPE_END:    slice.wBadSliceChopping = 2; break;
      case PIPE_SLICE_BUFFER_PLACEMENT_TYPE_MIDDLE: slice.wBadSliceChopping = 3; break;
      default: slice.wBadSliceChopping = 0; break;
      }
      slice.BSNALunitDataLocation = offset;
      slice.SliceBytesInBuffer = picture->slice_parameter.slice_data_size[i] + 3;
      offset += slice.SliceBytesInBuffer +
                picture->slice_parameter.slice_data_offset[i];
   }
   return slices;
}

static void
decoder_decode_bitstream(struct pipe_video_codec *base,
                         struct pipe_video_buffer *target,
                         struct pipe_picture_desc *picture,
                         unsigned num_buffers,
                         const void *const *buffers,
                         const unsigned *sizes)
{
   auto *codec = reinterpret_cast<svga_video_codec *>(base);
   auto *h264 = reinterpret_cast<pipe_h264_picture_desc *>(picture);
   auto *target_data = buffer_data(target);
   if (!target_data || !target_data->defined || !h264->pps ||
       !h264->slice_parameter.slice_info_present)
      return;

   DXVA_PicParams_H264 params =
      svga_dxva_picparams_from_pipe(++codec->feedback, base->profile,
                                    base->width, base->height, h264);
   params.CurrPic.Index7Bits = target_data->view_id;
   for (unsigned i = 0; i < 16; ++i) {
      if (params.RefFrameList[i].bPicEntry == 0xff)
         continue;
      auto *reference = buffer_data(h264->ref[i]);
      if (!reference || !reference->defined) {
         params.RefFrameList[i].bPicEntry = 0xff;
         continue;
      }
      params.RefFrameList[i].Index7Bits = reference->view_id;
   }

   DXVA_Qmatrix_H264 matrix = {};
   svga_dxva_qmatrix_from_pipe(h264, matrix);
   auto slices = make_slice_control(h264);
   auto bitstream = join_bitstream(num_buffers, buffers, sizes);
   if (!upload_argument(codec, 0, &params, sizeof(params)) ||
       !upload_argument(codec, 1, &matrix, sizeof(matrix)) ||
       !upload_argument(codec, 2, slices.data(), slices.size() * sizeof(slices[0])) ||
       !upload_argument(codec, 3, bitstream.data(), bitstream.size()))
      return;

   const uint32_t types[4] = {
      VBSVGA3D_VD_BUFFER_PICTURE_PARAMETERS,
      VBSVGA3D_VD_BUFFER_INVERSE_QUANTIZATION_MATRIX,
      VBSVGA3D_VD_BUFFER_SLICE_CONTROL,
      VBSVGA3D_VD_BUFFER_BITSTREAM,
   };
   const uint32_t argument_sizes[4] = {
      sizeof(params), sizeof(matrix),
      static_cast<uint32_t>(slices.size() * sizeof(slices[0])),
      static_cast<uint32_t>(bitstream.size()),
   };
   struct svga_winsys_surface *argument_surfaces[4];
   for (unsigned i = 0; i < 4; ++i) {
      /*
       * Resolving a buffer handle can emit and commit an SVGA upload command.
       * Do that before reserving the decoder submit packet so a nested FIFO
       * reservation cannot overwrite the packet being assembled.
       */
      argument_surfaces[i] = argument_surface(codec, i);
      if (!argument_surfaces[i])
         return;
   }

   const unsigned command_size =
      sizeof(VBSVGA3dCmdDXVideoDecoderSubmitBuffers) +
      4 * sizeof(VBSVGA3dVideoDecoderBufferDesc);
   auto *cmd = static_cast<VBSVGA3dCmdDXVideoDecoderSubmitBuffers *>(
      SVGA3D_FIFOReserve(codec->svga->swc,
                         VBSVGA_3D_CMD_DX_VIDEO_DECODER_SUBMIT_BUFFERS,
                         command_size, 4));
   if (!cmd)
      return;
   cmd->videoDecoderId = codec->decoder_id;
   auto *descriptors =
      reinterpret_cast<VBSVGA3dVideoDecoderBufferDesc *>(cmd + 1);
   std::memset(descriptors, 0, 4 * sizeof(*descriptors));
   for (unsigned i = 0; i < 4; ++i) {
      descriptors[i].bufferType = types[i];
      descriptors[i].dataSize = argument_sizes[i];
      codec->svga->swc->surface_relocation(
         codec->svga->swc, &descriptors[i].sidBuffer, nullptr,
         argument_surfaces[i], SVGA_RELOC_READ);
   }
   codec->svga->swc->commit(codec->svga->swc);
}

static int
decoder_end_frame(struct pipe_video_codec *base,
                  struct pipe_video_buffer *,
                  struct pipe_picture_desc *)
{
   auto *codec = reinterpret_cast<svga_video_codec *>(base);
   auto *cmd = static_cast<VBSVGA3dCmdDXVideoDecoderEndFrame *>(
      SVGA3D_FIFOReserve(codec->svga->swc,
                         VBSVGA_3D_CMD_DX_VIDEO_DECODER_END_FRAME,
                         sizeof(VBSVGA3dCmdDXVideoDecoderEndFrame), 0));
   if (!cmd)
      return -1;
   cmd->videoDecoderId = codec->decoder_id;
   codec->svga->swc->commit(codec->svga->swc);
   codec->base.context->flush(
      codec->base.context,
      &codec->argument_fences[codec->argument_slot],
      0);
   return 0;
}

static void
decoder_flush(struct pipe_video_codec *base)
{
   base->context->flush(base->context, nullptr, 0);
}

static void
decoder_destroy(struct pipe_video_codec *base)
{
   auto *codec = reinterpret_cast<svga_video_codec *>(base);
   auto *cmd = static_cast<VBSVGA3dCmdDXDestroyVideoDecoder *>(
      SVGA3D_FIFOReserve(codec->svga->swc,
                         VBSVGA_3D_CMD_DX_DESTROY_VIDEO_DECODER,
                         sizeof(VBSVGA3dCmdDXDestroyVideoDecoder), 0));
   if (cmd) {
      cmd->videoDecoderId = codec->decoder_id;
      codec->svga->swc->commit(codec->svga->swc);
   }
   for (unsigned slot = 0;
        slot < svga_video_codec::argument_slot_count;
        ++slot) {
      for (auto *&resource : codec->arguments[slot])
         pipe_resource_reference(&resource, nullptr);
      codec->base.context->screen->fence_reference(
         codec->base.context->screen,
         &codec->argument_fences[slot],
         nullptr);
   }
   FREE(codec);
}

extern "C" struct pipe_video_codec *
svga_video_create_codec(struct pipe_context *context,
                        const struct pipe_video_codec *templ)
{
   VBSVGA3dVideoDecoderDesc desc = {};
   desc.DecodeProfile = dxva_h264_vld_no_fgt;
   desc.SampleWidth = align(templ->width, 16);
   desc.SampleHeight = align(templ->height, 16);
   desc.OutputFormat = SVGA3D_NV12;
   VBSVGA3dVideoDecoderConfig config = {};

   if (!svga_has_vbox_video(context->screen)) {
      std::fprintf(stderr, "T1OS VMSVGA video: capability gate failed\n");
      return nullptr;
   }
   if (templ->entrypoint != PIPE_VIDEO_ENTRYPOINT_BITSTREAM) {
      std::fprintf(stderr, "T1OS VMSVGA video: unsupported entrypoint\n");
      return nullptr;
   }
   if (u_reduce_video_profile(templ->profile) != PIPE_VIDEO_FORMAT_MPEG4_AVC) {
      std::fprintf(stderr, "T1OS VMSVGA video: unsupported codec profile\n");
      return nullptr;
   }
   /*
    * The decoder-config capability is the authoritative combined check for
    * profile, output format, dimensions, and host decoder configuration.
    * Query it directly.  A separate profile-list transaction is redundant
    * and causes needless lifetime churn in VirtualBox's small query MOB pool.
    */
   if (!svga_vbox_video_decoder_config(context, desc, &config)) {
      std::fprintf(stderr, "T1OS VMSVGA video: host config gate failed\n");
      return nullptr;
   }

   auto *codec = CALLOC_STRUCT(svga_video_codec);
   if (!codec)
      return nullptr;
   codec->base = *templ;
   codec->base.context = context;
   codec->base.width = align(templ->width, 16);
   codec->base.height = align(templ->height, 16);
   codec->base.destroy = decoder_destroy;
   codec->base.begin_frame = decoder_begin_frame;
   codec->base.decode_bitstream = decoder_decode_bitstream;
   codec->base.end_frame = decoder_end_frame;
   codec->base.flush = decoder_flush;
   codec->svga = svga_context(context);
   codec->decoder_id = 0;
   codec->profile = dxva_h264_vld_no_fgt;

   auto *cmd = static_cast<VBSVGA3dCmdDXDefineVideoDecoder *>(
      SVGA3D_FIFOReserve(codec->svga->swc,
                         VBSVGA_3D_CMD_DX_DEFINE_VIDEO_DECODER,
                         sizeof(VBSVGA3dCmdDXDefineVideoDecoder), 0));
   if (!cmd) {
      FREE(codec);
      return nullptr;
   }
   std::memset(cmd, 0, sizeof(*cmd));
   cmd->videoDecoderId = codec->decoder_id;
   cmd->desc = desc;
   cmd->config = config;
   codec->svga->swc->commit(codec->svga->swc);
   std::fprintf(
      stderr,
      "T1OS VMSVGA video: decoder definition submitted %ux%u\n",
      desc.SampleWidth,
      desc.SampleHeight);
   return &codec->base;
}
