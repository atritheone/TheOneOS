// Copyright 2026 The One OS Authors
// Use of this source code is governed by a BSD-style license.

#ifndef CONTENT_BROWSER_GPU_T1OS_MEDIA_DECODE_BROKER_H_
#define CONTENT_BROWSER_GPU_T1OS_MEDIA_DECODE_BROKER_H_

#include <vector>

#include "base/files/scoped_file.h"

namespace base {
class CommandLine;
}

namespace content {

struct T1OSPresentationDescriptors {
  base::ScopedFD socket;
  base::ScopedFD render_node;
};

// Opens the bounded T1OS media-service connection pool in the unsandboxed
// browser process. Each descriptor is connected, CLOEXEC, and intended to be
// moved into ChildProcessLauncherFileData for one sandboxed GPU-process launch.
// An empty vector means the feature is disabled or the service is unavailable.
std::vector<base::ScopedFD> ConnectT1OSMediaDecoderPool(
    const base::CommandLine& browser_command_line);

// Preauthorizes the T1OS WindowServer presentation channel and opens the
// selected DRM render node before the GPU sandbox is entered.
T1OSPresentationDescriptors ConnectT1OSPresentationBridge(
    const base::CommandLine& browser_command_line);

}  // namespace content

#endif  // CONTENT_BROWSER_GPU_T1OS_MEDIA_DECODE_BROKER_H_
