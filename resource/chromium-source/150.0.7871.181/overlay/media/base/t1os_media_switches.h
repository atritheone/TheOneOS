// Copyright 2026 The One OS Authors
// Use of this source code is governed by a BSD-style license.

#ifndef MEDIA_BASE_T1OS_MEDIA_SWITCHES_H_
#define MEDIA_BASE_T1OS_MEDIA_SWITCHES_H_

#include <stddef.h>

#include "base/feature_list.h"
#include "media/base/media_export.h"

namespace media {

MEDIA_EXPORT BASE_DECLARE_FEATURE(kT1OSVideoDecoder);
// Authorizes the T1OS RGB presentation bridge independently from video
// decoding.  Keeping these features separate is intentional: linear-memory
// decode can be validated without changing Chromium's presentation path, and
// hardware presentation can be validated without exposing the decode service.
MEDIA_EXPORT BASE_DECLARE_FEATURE(kT1OSNvidiaPresentation);

// Browser-process-only service discovery. GpuProcessHost consumes this switch
// and passes connected sockets to the sandboxed GPU process. It must never be
// copied to the GPU command line.
inline constexpr char kT1OSVideoDecodeSocketSwitch[] =
    "t1os-video-decode-socket";
// Browser-side copy of the exact output contract. The broker verifies this
// value against the inherited environment before opening the descriptor pool;
// the GPU process then independently derives its HELLO requirements from the
// environment. This prevents a launch-policy/decoder-policy split brain.
inline constexpr char kT1OSVideoDecodeOutputSwitch[] =
    "t1os-video-decode-output";

// Browser-process-only T1OS presentation discovery. The browser validates and
// opens both resources, then passes only the connected socket and render-node
// descriptor to the sandboxed GPU process.
inline constexpr char kT1OSPresentationSocketSwitch[] =
    "t1os-presentation-socket";
inline constexpr char kT1OSPresentationTokenSwitch[] =
    "t1os-presentation-token";
inline constexpr char kT1OSPresentationRenderNodeSwitch[] =
    "t1os-presentation-render-node";

// Inherited by the sandboxed GPU process. The launcher accepts only these two
// values and the connection repeats that fail-closed validation before choosing
// the T1MD HELLO feature set. Absence selects linear memory; DMA-BUF is never an
// implicit default.
inline constexpr char kT1OSMediaDecodeOutputEnvironment[] =
    "T1OS_MEDIA_DECODE_OUTPUT";
inline constexpr char kT1OSMediaDecodeOutputLinearMemory[] = "linear-memory";
inline constexpr char kT1OSMediaDecodeOutputDmaBuf[] = "dma-buf";

inline constexpr char kT1OSMediaDecodeDescriptorPrefix[] = "t1os-media-decode-";
// Match the media service's advertised session ceiling.  Chromium opens the
// complete descriptor pool atomically before the GPU sandbox is entered, so
// this is also the maximum number of simultaneous hardware decoder clients.
inline constexpr size_t kT1OSMediaDecodeDescriptorPoolSize = 8;
inline constexpr char kT1OSPresentationDescriptor[] = "t1os-presentation";
inline constexpr char kT1OSPresentationRenderNodeDescriptor[] =
    "t1os-presentation-render-node";

inline constexpr char kT1OSMediaDecoderBuildMarker[] =
    "T1OS_MEDIA_DECODER=T1MD/1;brokered_socket=1;pool=8;"
    "chromium=24b04c927b23c39cf9c5227cc8dc6f64a744c8e9;"
    "protocol_sha256="
    "11a319c26e499415cf39a3b6b5c59c3801b2e91859500472b92c6be1fcaceba0;"
    "source_sha256="
    "597ed8a32051a65e12a3582801369c8caa9dabcf8ef7e36720cfaf1be3919f4e";

}  // namespace media

#endif  // MEDIA_BASE_T1OS_MEDIA_SWITCHES_H_
