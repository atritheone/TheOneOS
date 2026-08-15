// Copyright 2026 The One OS Authors
// Use of this source code is governed by a BSD-style license.

#include <fcntl.h>
#include <linux/memfd.h>
#include <sys/syscall.h>
#include <unistd.h>

#include "sandbox/linux/bpf_dsl/bpf_dsl.h"
#include "sandbox/linux/seccomp-bpf-helpers/sigsys_handlers.h"
#include "sandbox/linux/seccomp-bpf/bpf_tests.h"
#include "sandbox/linux/system_headers/linux_syscalls.h"
#include "sandbox/linux/tests/unit_tests.h"
#include "sandbox/policy/linux/bpf_gpu_policy_linux.h"

#if defined(__NR_fcntl) && defined(__NR_memfd_create)

namespace sandbox::policy {
namespace {

using bpf_dsl::Allow;
using bpf_dsl::ResultExpr;

// Exercise the production GPU fcntl expression while leaving setup syscalls
// available to the forked BPF test process. RGB DMA-BUF presentation requires
// no presentation-specific priority-inheritance futex exception.
class T1OSGpuSealPolicyWrapper : public bpf_dsl::Policy {
 public:
  ResultExpr EvaluateSyscall(int sysno) const override {
    if (sysno == __NR_fcntl) {
      return policy_.EvaluateSyscall(sysno);
    }
    return Allow();
  }

 private:
  GpuProcessPolicy policy_{MremapPolicy::kBlock};
};

BPF_TEST_C(T1OSGpuSealPolicy,
           ImmutableAccessUnitSealMaskAllowed,
           T1OSGpuSealPolicyWrapper) {
  const int fd = syscall(__NR_memfd_create, "t1os-seal-test",
                         MFD_CLOEXEC | MFD_ALLOW_SEALING);
  BPF_ASSERT_GE(fd, 0);
  BPF_ASSERT_EQ(0, ftruncate(fd, 4096));
  constexpr int kAccessUnitSeals =
      F_SEAL_SEAL | F_SEAL_SHRINK | F_SEAL_GROW | F_SEAL_WRITE;
  BPF_ASSERT_EQ(0, fcntl(fd, F_ADD_SEALS, kAccessUnitSeals));
  close(fd);
}

// The extension is deliberately restriction-only: it permits F_SEAL_WRITE in
// the exact F_ADD_SEALS argument mask but does not open arbitrary fcntl flags.
BPF_DEATH_TEST_C(T1OSGpuSealPolicy,
                 UnrelatedSealFlagDenied,
                 DEATH_SEGV_MESSAGE(GetErrorMessageContentForTests()),
                 T1OSGpuSealPolicyWrapper) {
  const int fd = syscall(__NR_memfd_create, "t1os-bad-seal-test",
                         MFD_CLOEXEC | MFD_ALLOW_SEALING);
  BPF_ASSERT_GE(fd, 0);
  fcntl(fd, F_ADD_SEALS, static_cast<unsigned long>(1) << 31);
}

}  // namespace
}  // namespace sandbox::policy

#endif  // defined(__NR_fcntl) && defined(__NR_memfd_create)
