// Copyright 2026 The One OS Authors
// Use of this source code is governed by a BSD-style license.

#include "content/browser/gpu/t1os_media_decode_broker.h"

#include "build/build_config.h"

#if BUILDFLAG(IS_LINUX)

#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stddef.h>
#include <sys/socket.h>
#include <sys/un.h>

#include <string>
#include <utility>

#include "base/command_line.h"
#include "base/containers/span.h"
#include "base/environment.h"
#include "base/feature_list.h"
#include "base/logging.h"
#include "base/posix/eintr_wrapper.h"
#include "media/base/t1os_media_switches.h"

namespace content {
namespace {

constexpr int kConnectTimeoutMilliseconds = 250;
constexpr int kPresentationAuthorizeTimeoutMilliseconds = 1000;

base::ScopedFD ConnectOne(const std::string& path) {
  base::ScopedFD socket_fd(
      socket(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC | SOCK_NONBLOCK, 0));
  if (!socket_fd.is_valid()) {
    PLOG(ERROR) << "T1OS media broker could not create SOCK_SEQPACKET";
    return {};
  }

  sockaddr_un address = {};
  address.sun_family = AF_UNIX;
  if (path.size() >= sizeof(address.sun_path)) {
    LOG(ERROR) << "T1OS media broker socket path is too long";
    return {};
  }
  auto socket_path = base::span(address.sun_path);
  socket_path.copy_prefix_from(base::span(path));
  socket_path[path.size()] = '\0';

  const socklen_t address_size =
      static_cast<socklen_t>(offsetof(sockaddr_un, sun_path) + path.size() + 1);
  int result = HANDLE_EINTR(connect(
      socket_fd.get(), reinterpret_cast<sockaddr*>(&address), address_size));
  if (result != 0 && errno == EINPROGRESS) {
    pollfd event = {.fd = socket_fd.get(), .events = POLLOUT, .revents = 0};
    result = HANDLE_EINTR(poll(&event, 1, kConnectTimeoutMilliseconds));
    if (result > 0) {
      int socket_error = 0;
      socklen_t socket_error_size = sizeof(socket_error);
      if (getsockopt(socket_fd.get(), SOL_SOCKET, SO_ERROR, &socket_error,
                     &socket_error_size) != 0) {
        result = -1;
      } else if (socket_error != 0) {
        errno = socket_error;
        result = -1;
      } else {
        result = 0;
      }
    } else if (result == 0) {
      errno = ETIMEDOUT;
      result = -1;
    }
  }
  if (result != 0) {
    PLOG(WARNING) << "T1OS media broker could not connect";
    return {};
  }

  const int flags = fcntl(socket_fd.get(), F_GETFL);
  if (flags < 0 ||
      HANDLE_EINTR(fcntl(socket_fd.get(), F_SETFL, flags & ~O_NONBLOCK)) < 0) {
    PLOG(ERROR) << "T1OS media broker could not restore blocking mode";
    return {};
  }
  return socket_fd;
}

bool IsSafeToken(const std::string& token) {
  if (token.size() < 32 || token.size() > 256) {
    return false;
  }
  for (const char value : token) {
    if (!((value >= 'a' && value <= 'z') ||
          (value >= 'A' && value <= 'Z') ||
          (value >= '0' && value <= '9') || value == '-' || value == '_')) {
      return false;
    }
  }
  return true;
}

base::ScopedFD ConnectAuthorizedPresentation(const std::string& path,
                                             const std::string& token) {
  base::ScopedFD socket_fd = ConnectOne(path);
  if (!socket_fd.is_valid()) {
    return {};
  }
  const std::string request = "{\"op\":\"auth\",\"token\":\"" + token +
                              "\"}";
  if (HANDLE_EINTR(send(socket_fd.get(), request.data(), request.size(),
                        MSG_NOSIGNAL)) !=
      static_cast<ssize_t>(request.size())) {
    PLOG(ERROR) << "T1OS presentation broker could not authorize socket";
    return {};
  }
  pollfd event = {.fd = socket_fd.get(), .events = POLLIN, .revents = 0};
  const int ready = HANDLE_EINTR(
      poll(&event, 1, kPresentationAuthorizeTimeoutMilliseconds));
  if (ready <= 0 || !(event.revents & POLLIN)) {
    LOG(ERROR) << "T1OS presentation authorization timed out";
    return {};
  }
  char reply[256] = {};
  const ssize_t length = HANDLE_EINTR(recv(socket_fd.get(), reply,
                                           sizeof(reply) - 1, 0));
  if (length <= 0 ||
      std::string(reply, static_cast<size_t>(length)).find(
          "\"op\":\"authorized\"") == std::string::npos) {
    LOG(ERROR) << "T1OS presentation authorization was rejected";
    return {};
  }
  return socket_fd;
}

}  // namespace

std::vector<base::ScopedFD> ConnectT1OSMediaDecoderPool(
    const base::CommandLine& browser_command_line) {
  std::vector<base::ScopedFD> sockets;
  if (!base::FeatureList::IsEnabled(media::kT1OSVideoDecoder) ||
      !browser_command_line.HasSwitch(media::kT1OSVideoDecodeSocketSwitch) ||
      !browser_command_line.HasSwitch(media::kT1OSVideoDecodeOutputSwitch)) {
    return sockets;
  }

  const std::string requested_output =
      browser_command_line.GetSwitchValueASCII(
          media::kT1OSVideoDecodeOutputSwitch);
  auto environment = base::Environment::Create();
  const auto inherited_output =
      environment->GetVar(media::kT1OSMediaDecodeOutputEnvironment);
  if ((requested_output != media::kT1OSMediaDecodeOutputDmaBuf &&
       requested_output != media::kT1OSMediaDecodeOutputLinearMemory) ||
      !inherited_output || *inherited_output != requested_output) {
    LOG(ERROR) << "T1OS media broker rejected an inconsistent output mode";
    return sockets;
  }

  const std::string path = browser_command_line.GetSwitchValueASCII(
      media::kT1OSVideoDecodeSocketSwitch);
  if (path.empty() || path.front() != '/' ||
      path.find('\0') != std::string::npos) {
    LOG(ERROR) << "T1OS media broker rejected an invalid socket path";
    return sockets;
  }

  LOG(INFO) << media::kT1OSMediaDecoderBuildMarker;
  sockets.reserve(media::kT1OSMediaDecodeDescriptorPoolSize);
  for (size_t index = 0; index < media::kT1OSMediaDecodeDescriptorPoolSize;
       ++index) {
    auto socket_fd = ConnectOne(path);
    if (!socket_fd.is_valid()) {
      sockets.clear();
      break;
    }
    sockets.push_back(std::move(socket_fd));
  }
  if (sockets.size() != media::kT1OSMediaDecodeDescriptorPoolSize) {
    sockets.clear();
    LOG(ERROR) << "T1OS media decoder requires an atomic eight-connection "
                  "broker pool";
  } else {
    LOG(INFO) << "T1OS media broker prepared " << sockets.size()
              << " GPU-process decoder connections";
  }
  return sockets;
}

T1OSPresentationDescriptors ConnectT1OSPresentationBridge(
    const base::CommandLine& browser_command_line) {
  T1OSPresentationDescriptors descriptors;
  if (!base::FeatureList::IsEnabled(media::kT1OSNvidiaPresentation) ||
      !browser_command_line.HasSwitch(media::kT1OSPresentationSocketSwitch) ||
      !browser_command_line.HasSwitch(media::kT1OSPresentationTokenSwitch) ||
      !browser_command_line.HasSwitch(
          media::kT1OSPresentationRenderNodeSwitch)) {
    return descriptors;
  }
  const std::string socket_path = browser_command_line.GetSwitchValueASCII(
      media::kT1OSPresentationSocketSwitch);
  const std::string token = browser_command_line.GetSwitchValueASCII(
      media::kT1OSPresentationTokenSwitch);
  const std::string render_node = browser_command_line.GetSwitchValueASCII(
      media::kT1OSPresentationRenderNodeSwitch);
  if (socket_path.empty() || socket_path.front() != '/' ||
      socket_path.find('\0') != std::string::npos || !IsSafeToken(token) ||
      !(render_node.starts_with("/the one/drivers/nodes/dri/renderD") ||
        render_node.starts_with("/the one/drivers/dri/renderD")) ||
      render_node.find('\0') != std::string::npos) {
    LOG(ERROR) << "T1OS presentation broker rejected invalid discovery data";
    return descriptors;
  }
  descriptors.socket = ConnectAuthorizedPresentation(socket_path, token);
  if (!descriptors.socket.is_valid()) {
    return descriptors;
  }
  descriptors.render_node.reset(
      HANDLE_EINTR(open(render_node.c_str(), O_RDWR | O_CLOEXEC | O_NOFOLLOW)));
  if (!descriptors.render_node.is_valid()) {
    PLOG(ERROR) << "T1OS presentation broker could not open render node";
    descriptors.socket.reset();
    return descriptors;
  }
  LOG(INFO) << "T1OS_PRESENTATION_BRIDGE brokered_socket=1 render_node=1";
  return descriptors;
}

}  // namespace content

#endif  // BUILDFLAG(IS_LINUX)
