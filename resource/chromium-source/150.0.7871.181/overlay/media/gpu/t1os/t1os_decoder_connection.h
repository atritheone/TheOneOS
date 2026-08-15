// Copyright 2026 The One OS Authors
// Use of this source code is governed by a BSD-style license.

#ifndef MEDIA_GPU_T1OS_T1OS_DECODER_CONNECTION_H_
#define MEDIA_GPU_T1OS_T1OS_DECODER_CONNECTION_H_

#include <stddef.h>
#include <stdint.h>

#include <array>
#include <optional>
#include <string>
#include <vector>

#include "base/containers/span.h"
#include "base/files/memory_mapped_file.h"
#include "base/files/scoped_file.h"
#include "base/functional/callback.h"
#include "base/memory/ref_counted_delete_on_sequence.h"
#include "base/memory/scoped_refptr.h"
#include "base/no_destructor.h"
#include "base/synchronization/lock.h"
#include "base/thread_annotations.h"
#include "base/threading/thread.h"
#include "media/base/supported_video_decoder_config.h"
#include "media/gpu/media_gpu_export.h"
#include "media/gpu/t1os/t1_media_decode_protocol.h"

namespace base {
class SequencedTaskRunner;
}

namespace media {

class T1OSDecoderConnectionTestPeer;

struct MEDIA_GPU_EXPORT T1OSDecoderPacket {
  t1_media_message_header header = {};
  std::vector<uint8_t> payload;
  std::vector<base::ScopedFD> descriptors;
};

// Owns one authenticated T1MD connection. Exactly one T1OSVideoDecoder may use
// it at a time. The object can survive the decoder while SharedImages retain
// native surfaces; it returns to the pool only after every RELEASE is sent.
class MEDIA_GPU_EXPORT T1OSDecoderConnection final
    : public base::RefCountedDeleteOnSequence<T1OSDecoderConnection> {
 public:
  using PacketCB = base::RepeatingCallback<void(T1OSDecoderPacket)>;
  using DisconnectCB = base::OnceCallback<void()>;
  using FrameCreditCB = base::RepeatingClosure;
  using RecycleCB =
      base::OnceCallback<void(scoped_refptr<T1OSDecoderConnection>)>;

  T1OSDecoderConnection(
      base::ScopedFD socket,
      scoped_refptr<base::SequencedTaskRunner> owner_task_runner);

  bool EnsureHandshake();
  bool is_ready() const;
  uint64_t session() const;
  t1_media_capabilities capabilities() const;

  bool SetClient(PacketCB packet_cb,
                 DisconnectCB disconnect_cb,
                 FrameCreditCB frame_credit_cb);
  void ClearClient();
  // Permanently closes a connection which cannot be proven quiescent. This is
  // used instead of DESTROY/recycle when the decoder is torn down with an
  // outstanding CREATE, DECODE, FLUSH, or RESET operation.
  void Abandon();

  // Allocates a strictly increasing, nonzero request ID while holding the same
  // lock used for sendmsg(), then sends the packet. This prevents concurrent
  // frame-release and decode traffic from reaching the service out of order.
  std::optional<uint64_t> Send(uint16_t type,
                               uint64_t session,
                               uint64_t generation,
                               uint32_t flags,
                               base::span<const uint8_t> payload,
                               base::span<const int> descriptors = {});

  bool NoteFrameReady();
  bool HasFrameCredit(size_t reserved_decode_frames = 0) const;
  void ReleaseFrame(uint64_t session, uint64_t generation, uint64_t frame_id);
  void ReleaseUntrackedFrame(uint64_t session,
                             uint64_t generation,
                             uint64_t frame_id);

  // Stops accepting work for the current session. DESTROY and recycle are
  // deferred until all SharedImage-backed frames have called ReleaseFrame().
  void BeginRecycle(uint64_t session,
                    uint64_t generation,
                    RecycleCB recycle_cb);

 private:
  friend class base::RefCountedDeleteOnSequence<T1OSDecoderConnection>;
  friend class base::DeleteHelper<T1OSDecoderConnection>;
  friend class T1OSDecoderConnectionTestPeer;
  ~T1OSDecoderConnection();

  bool SendHello();
  bool SendHelloLocked() EXCLUSIVE_LOCKS_REQUIRED(send_lock_);
  std::optional<uint64_t> SendPacketLocked(uint16_t type,
                                           uint64_t session,
                                           uint64_t generation,
                                           uint32_t flags,
                                           base::span<const uint8_t> payload,
                                           base::span<const int> descriptors)
      EXCLUSIVE_LOCKS_REQUIRED(send_lock_);
  std::optional<uint64_t> NextRequestLocked()
      EXCLUSIVE_LOCKS_REQUIRED(send_lock_);
  bool ValidateCapabilitiesPacket(const T1OSDecoderPacket& packet,
                                  t1_media_capabilities* capabilities,
                                  uint64_t* session) const;
  std::optional<T1OSDecoderPacket> ReceivePacketBlocking();
  bool StartReader();
  void ReadLoop();
  bool HandleInternalPacket(T1OSDecoderPacket* packet);
  void NotifyDisconnect();
  void DeliverPacket(PacketCB callback, T1OSDecoderPacket packet);
  void MaybeStartDestroy();
  void StartPostDestroyHandshake();
  void FinishRecycleAfterHandshake();
  void OnRecycleTimeout(uint64_t request, bool waiting_for_capabilities);

  base::ScopedFD socket_;
  const scoped_refptr<base::SequencedTaskRunner> owner_task_runner_;
  base::Thread reader_thread_{"T1OS media decoder socket"};

  mutable base::Lock state_lock_;
  bool ready_ GUARDED_BY(state_lock_) = false;
  bool reader_started_ GUARDED_BY(state_lock_) = false;
  bool disconnected_ GUARDED_BY(state_lock_) = false;
  uint64_t session_ GUARDED_BY(state_lock_) = 0;
  t1_media_capabilities capabilities_ GUARDED_BY(state_lock_) = {};
  PacketCB packet_cb_ GUARDED_BY(state_lock_);
  DisconnectCB disconnect_cb_ GUARDED_BY(state_lock_);
  FrameCreditCB frame_credit_cb_ GUARDED_BY(state_lock_);
  RecycleCB recycle_cb_ GUARDED_BY(state_lock_);
  uint64_t recycle_session_ GUARDED_BY(state_lock_) = 0;
  uint64_t recycle_generation_ GUARDED_BY(state_lock_) = 0;
  uint64_t destroy_request_ GUARDED_BY(state_lock_) = 0;
  uint64_t hello_request_ GUARDED_BY(state_lock_) = 0;
  bool awaiting_post_destroy_capabilities_ GUARDED_BY(state_lock_) = false;
  size_t in_flight_frames_ GUARDED_BY(state_lock_) = 0;
  size_t queued_packets_ GUARDED_BY(state_lock_) = 0;
  size_t queued_descriptors_ GUARDED_BY(state_lock_) = 0;
  base::Lock send_lock_;
  // Serializes shutdown() with the reader's final close. The send lock
  // separately prevents close-vs-send descriptor reuse.
  base::Lock socket_lifecycle_lock_;
  uint64_t next_request_ GUARDED_BY(send_lock_) = 1;
  bool request_ids_exhausted_ GUARDED_BY(send_lock_) = false;
};

class MEDIA_GPU_EXPORT T1OSDecoderConnectionPool {
 public:
  static T1OSDecoderConnectionPool& GetInstance();

  T1OSDecoderConnectionPool(const T1OSDecoderConnectionPool&) = delete;
  T1OSDecoderConnectionPool& operator=(const T1OSDecoderConnectionPool&) =
      delete;

  bool IsAvailable();
  SupportedVideoDecoderConfigs GetSupportedConfigs();
  scoped_refptr<T1OSDecoderConnection> Acquire();
  void Recycle(scoped_refptr<T1OSDecoderConnection> connection);
  size_t available_for_testing() const;

 private:
  friend class base::NoDestructor<T1OSDecoderConnectionPool>;
  T1OSDecoderConnectionPool();
  ~T1OSDecoderConnectionPool();

  void Initialize();
  mutable base::Lock lock_;
  bool initialized_ GUARDED_BY(lock_) = false;
  bool supported_ GUARDED_BY(lock_) = false;
  t1_media_capabilities capabilities_ GUARDED_BY(lock_) = {};
  std::vector<scoped_refptr<T1OSDecoderConnection>> available_
      GUARDED_BY(lock_);
};

MEDIA_GPU_EXPORT std::optional<VideoCodecProfile> T1OSProfileToChromiumProfile(
    uint32_t profile);
MEDIA_GPU_EXPORT SupportedVideoDecoderConfigs
T1OSConfigsFromCapabilities(const t1_media_capabilities& capabilities);

}  // namespace media

#endif  // MEDIA_GPU_T1OS_T1OS_DECODER_CONNECTION_H_
