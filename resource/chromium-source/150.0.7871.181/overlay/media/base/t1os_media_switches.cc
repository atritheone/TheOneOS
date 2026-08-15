// Copyright 2026 The One OS Authors
// Use of this source code is governed by a BSD-style license.

#include "media/base/t1os_media_switches.h"

namespace media {

BASE_FEATURE(kT1OSVideoDecoder,
             "T1OSVideoDecoder",
             base::FEATURE_DISABLED_BY_DEFAULT);

BASE_FEATURE(kT1OSNvidiaPresentation,
             "T1OSNvidiaPresentation",
             base::FEATURE_DISABLED_BY_DEFAULT);

}  // namespace media
