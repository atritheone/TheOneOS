/*
 * SPDX-License-Identifier: MIT
 */

#ifndef SVGA_VIDEO_H
#define SVGA_VIDEO_H

#include "pipe/p_video_codec.h"

struct pipe_context;
struct pipe_resource;
struct pipe_screen;
struct svga_context;
struct svga_winsys_surface;

#ifdef __cplusplus
extern "C" {
#endif

int
svga_video_get_param(struct pipe_screen *screen,
                     enum pipe_video_profile profile,
                     enum pipe_video_entrypoint entrypoint,
                     enum pipe_video_cap param);

bool
svga_video_is_format_supported(struct pipe_screen *screen,
                               enum pipe_format format,
                               enum pipe_video_profile profile,
                               enum pipe_video_entrypoint entrypoint);

struct pipe_video_codec *
svga_video_create_codec(struct pipe_context *context,
                        const struct pipe_video_codec *templ);

struct pipe_video_buffer *
svga_video_create_buffer(struct pipe_context *context,
                         const struct pipe_video_buffer *templ);

struct svga_winsys_surface *
svga_video_texture_handle(struct pipe_resource *resource);

struct svga_winsys_surface *
svga_video_argument_handle(struct svga_context *svga,
                           struct pipe_resource *resource);

#ifdef __cplusplus
}
#endif

#endif
