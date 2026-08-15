// Copyright 2026 The One OS Authors
// Use of this source code is governed by a BSD-style license.

#ifndef MEDIA_GPU_T1OS_T1OS_VIDEO_DECODER_H_
#define MEDIA_GPU_T1OS_T1OS_VIDEO_DECODER_H_

#include <stddef.h>
#include <stdint.h>

#include <deque>
#include <memory>
#include <optional>
#include <vector>

#include "base/containers/flat_map.h"
#include "base/containers/flat_set.h"
#include "base/functional/callback.h"
#include "base/memory/weak_ptr.h"
#include "base/sequence_checker.h"
#include "media/base/supported_video_decoder_config.h"
#include "media/base/video_decoder.h"
#include "media/base/video_decoder_config.h"
#include "media/gpu/chromeos/frame_resource_converter.h"
#include "media/gpu/media_gpu_export.h"
#include "media/gpu/t1os/t1_media_decode_protocol.h"

namespace base {
class SequencedTaskRunner;
}

namespace media {

class MediaLog;
class T1OSDecoderConnection;
struct T1OSDecoderPacket;

class MEDIA_GPU_EXPORT T1OSVideoDecoder final : public VideoDecoder {
 public:
  static bool IsAvailable();
  static SupportedVideoDecoderConfigs GetSupportedConfigs();
  static std::unique_ptr<VideoDecoder> Create(
      scoped_refptr<base::SequencedTaskRunner> task_runner,
      std::unique_ptr<MediaLog> media_log,
      std::unique_ptr<FrameResourceConverter> frame_converter);
  static std::unique_ptr<T1OSVideoDecoder> CreateForTesting(
      scoped_refptr<base::SequencedTaskRunner> task_runner,
      std::unique_ptr<MediaLog> media_log,
      std::unique_ptr<FrameResourceConverter> frame_converter,
      scoped_refptr<T1OSDecoderConnection> connection);

  T1OSVideoDecoder(const T1OSVideoDecoder&) = delete;
  T1OSVideoDecoder& operator=(const T1OSVideoDecoder&) = delete;
  ~T1OSVideoDecoder() override;

  void Initialize(const VideoDecoderConfig& config,
                  bool low_delay,
                  CdmContext* cdm_context,
                  InitCB init_cb,
                  const OutputCB& output_cb,
                  const WaitingCB& waiting_cb) override;
  void Decode(scoped_refptr<DecoderBuffer> buffer, DecodeCB decode_cb) override;
  void Reset(base::OnceClosure closure) override;
  bool NeedsBitstreamConversion() const override;
  bool CanReadWithoutStalling() const override;
  int GetMaxDecodeRequests() const override;
  bool FramesHoldExternalResources() const override;
  bool IsPlatformDecoder() const override;
  VideoDecoderType GetDecoderType() const override;

 private:
  friend class T1OSVideoDecoderTestPeer;

  enum class OperationClass {
    kCreate,
    kDecode,
    kFlush,
    kReset,
  };
  struct PendingDecode {
    scoped_refptr<DecoderBuffer> buffer;
    DecodeCB callback;
  };

  T1OSVideoDecoder(scoped_refptr<base::SequencedTaskRunner> task_runner,
                   std::unique_ptr<MediaLog> media_log,
                   std::unique_ptr<FrameResourceConverter> frame_converter,
                   scoped_refptr<T1OSDecoderConnection> connection);

  bool SendCreate(const VideoDecoderConfig& config, bool low_delay);
  std::optional<uint64_t> SendDecodeBuffer(const DecoderBuffer& buffer);
  void RetireConnection(bool may_recycle);
  bool AcquireConnection();
  void DrainPendingDecodes();
  void OnFrameCreditAvailable(scoped_refptr<T1OSDecoderConnection> source,
                              uint64_t client_epoch);
  void ArmOperationTimeout(OperationClass operation, uint64_t request);
  void OnOperationTimeout(OperationClass operation,
                          uint64_t request,
                          uint64_t client_epoch,
                          uint64_t operation_epoch);

  void OnPacket(scoped_refptr<T1OSDecoderConnection> source,
                uint64_t client_epoch,
                T1OSDecoderPacket packet);
  void OnCreated(const T1OSDecoderPacket& packet);
  void OnDecodeDone(const T1OSDecoderPacket& packet);
  void OnFrame(T1OSDecoderPacket packet);
  void OnBackpressure(const T1OSDecoderPacket& packet);
  void OnFlushed(const T1OSDecoderPacket& packet);
  void OnResetDone(const T1OSDecoderPacket& packet);
  void OnServiceError(const T1OSDecoderPacket& packet);
  void OnDisconnected(scoped_refptr<T1OSDecoderConnection> source,
                      uint64_t client_epoch);
  void OnConvertedFrame(scoped_refptr<VideoFrame> frame);

  void Fail(DecoderStatus status);
  std::vector<DecodeCB> TakePendingDecodes();
  void AbortPendingDecodes();

  const scoped_refptr<base::SequencedTaskRunner> task_runner_;
  std::unique_ptr<MediaLog> media_log_;
  std::unique_ptr<FrameResourceConverter> frame_converter_;
  scoped_refptr<T1OSDecoderConnection> connection_;

  VideoDecoderConfig config_;
  OutputCB output_cb_;
  WaitingCB waiting_cb_;
  InitCB init_cb_;
  base::OnceClosure reset_cb_;
  base::flat_map<uint64_t, DecodeCB> decode_callbacks_;
  base::flat_set<uint64_t> frame_requests_;
  std::deque<PendingDecode> pending_credit_decodes_;

  uint64_t session_ = 0;
  uint64_t generation_ = 1;
  uint64_t create_request_ = 0;
  uint64_t reset_request_ = 0;
  uint64_t flush_request_ = 0;
  uint64_t backpressure_request_ = 0;
  uint64_t client_epoch_ = 0;
  uint64_t operation_epoch_ = 1;
  bool converter_initialized_ = false;
  bool create_sent_ = false;
  bool initialized_ = false;
  bool resetting_ = false;
  bool failed_ = false;
  int maximum_decode_requests_ = 1;
  size_t in_flight_decode_requests_ = 0;

  SEQUENCE_CHECKER(sequence_checker_);
  base::WeakPtrFactory<T1OSVideoDecoder> weak_factory_{this};
};

MEDIA_GPU_EXPORT uint32_t
ChromiumProfileToT1OSProfile(VideoCodecProfile profile);

// Protocol-boundary validators shared by packet handling and deterministic
// hostile-service tests. They deliberately accept only wire metadata and
// descriptor facts; no test-only behavior is compiled into the decoder.
MEDIA_GPU_EXPORT bool ValidateT1OSFrameLayout(const t1_media_frame& frame,
                                              size_t descriptor_count);
MEDIA_GPU_EXPORT bool IsValidT1OSDmaBufObject(int descriptor,
                                              uint64_t advertised_size);
MEDIA_GPU_EXPORT bool IsValidT1OSLinearMemoryObject(
    int descriptor,
    uint64_t advertised_size);
MEDIA_GPU_EXPORT bool IsCurrentT1OSDecoderClient(
    const T1OSDecoderConnection* source,
    const T1OSDecoderConnection* current,
    uint64_t source_epoch,
    uint64_t current_epoch);
MEDIA_GPU_EXPORT bool CanIssueT1OSDecode(size_t in_flight,
                                         int maximum_requests);

}  // namespace media

#endif  // MEDIA_GPU_T1OS_T1OS_VIDEO_DECODER_H_
