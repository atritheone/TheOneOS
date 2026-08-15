/*
 * SPDX-License-Identifier: MIT
 *
 * Small C bridge for SVGA headers which use C identifiers that are C++
 * keywords.  It keeps the decoder implementation type-safe without changing
 * the rest of Mesa's SVGA driver headers.
 */

#include "svga_context.h"
#include "svga_resource_buffer.h"
#include "svga_resource_texture.h"
#include "svga_video.h"

struct svga_winsys_surface *
svga_video_texture_handle(struct pipe_resource *resource)
{
   return svga_texture(resource)->handle;
}

struct svga_winsys_surface *
svga_video_argument_handle(struct svga_context *svga,
                           struct pipe_resource *resource)
{
   return svga_buffer_handle(svga, resource, 0);
}
