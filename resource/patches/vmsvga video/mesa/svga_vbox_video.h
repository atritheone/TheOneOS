/*
 * SPDX-License-Identifier: MIT
 *
 * VirtualBox VMSVGA video command wire definitions used by T1OS.
 * The protocol is transported inside the existing SVGA3D command stream.
 */

#ifndef SVGA_VBOX_VIDEO_H
#define SVGA_VBOX_VIDEO_H

#include <stdint.h>
#include "svga3d_types.h"

#define VBSVGA3D_CAP_3D    0x00000001u
#define VBSVGA3D_CAP_VIDEO 0x00000002u
#define VBSVGA_3D_CMD_BASE 1000000u
#define VBSVGA_3D_CMD_DX_DEFINE_VIDEO_PROCESSOR           (VBSVGA_3D_CMD_BASE + 0)
#define VBSVGA_3D_CMD_DX_DEFINE_VIDEO_DECODER_OUTPUT_VIEW (VBSVGA_3D_CMD_BASE + 1)
#define VBSVGA_3D_CMD_DX_DEFINE_VIDEO_DECODER             (VBSVGA_3D_CMD_BASE + 2)
#define VBSVGA_3D_CMD_DX_VIDEO_DECODER_BEGIN_FRAME        (VBSVGA_3D_CMD_BASE + 3)
#define VBSVGA_3D_CMD_DX_VIDEO_DECODER_SUBMIT_BUFFERS     (VBSVGA_3D_CMD_BASE + 4)
#define VBSVGA_3D_CMD_DX_VIDEO_DECODER_END_FRAME          (VBSVGA_3D_CMD_BASE + 5)
#define VBSVGA_3D_CMD_DX_DESTROY_VIDEO_DECODER            (VBSVGA_3D_CMD_BASE + 9)
#define VBSVGA_3D_CMD_DX_DESTROY_VIDEO_DECODER_OUTPUT_VIEW (VBSVGA_3D_CMD_BASE + 10)
#define VBSVGA_3D_CMD_DX_GET_VIDEO_CAPABILITY             (VBSVGA_3D_CMD_BASE + 33)

#define VBSVGA3D_VDOV_DIMENSION_TEXTURE2D 1u
#define VBSVGA3D_VD_BUFFER_PICTURE_PARAMETERS          0u
#define VBSVGA3D_VD_BUFFER_INVERSE_QUANTIZATION_MATRIX 4u
#define VBSVGA3D_VD_BUFFER_SLICE_CONTROL               5u
#define VBSVGA3D_VD_BUFFER_BITSTREAM                   6u
#define VBSVGA3D_VIDEO_CAPABILITY_DECODE_PROFILE       0u
#define VBSVGA3D_VIDEO_CAPABILITY_DECODE_CONFIG        1u

typedef struct {
   uint32_t data1;
   uint16_t data2;
   uint16_t data3;
   uint8_t data4[8];
} VBSVGA3dGuid;

typedef struct {
   VBSVGA3dGuid DecodeProfile;
   uint32_t ViewDimension;
   union {
      struct {
         uint32_t ArraySlice;
      } Texture2D;
      uint32_t pad[4];
   };
} VBSVGA3dVDOVDesc;

typedef struct {
   VBSVGA3dGuid DecodeProfile;
   uint32_t SampleWidth;
   uint32_t SampleHeight;
   SVGA3dSurfaceFormat OutputFormat;
} VBSVGA3dVideoDecoderDesc;

typedef struct {
   VBSVGA3dGuid guidConfigBitstreamEncryption;
   VBSVGA3dGuid guidConfigMBcontrolEncryption;
   VBSVGA3dGuid guidConfigResidDiffEncryption;
   uint32_t ConfigBitstreamRaw;
   uint32_t ConfigMBcontrolRasterOrder;
   uint32_t ConfigResidDiffHost;
   uint32_t ConfigSpatialResid8;
   uint32_t ConfigResid8Subtraction;
   uint32_t ConfigSpatialHost8or9Clipping;
   uint32_t ConfigSpatialResidInterleaved;
   uint32_t ConfigIntraResidUnsigned;
   uint32_t ConfigResidDiffAccelerator;
   uint32_t ConfigHostInverseScan;
   uint32_t ConfigSpecificIDCT;
   uint32_t Config4GroupedCoefs;
   uint16_t ConfigMinRenderTargetBuffCount;
   uint16_t ConfigDecoderSpecific;
} VBSVGA3dVideoDecoderConfig;

typedef struct {
   uint32_t videoDecoderOutputViewId;
   SVGA3dSurfaceId sid;
   VBSVGA3dVDOVDesc desc;
} VBSVGA3dCmdDXDefineVideoDecoderOutputView;

typedef struct {
   uint32_t videoDecoderId;
   VBSVGA3dVideoDecoderDesc desc;
   VBSVGA3dVideoDecoderConfig config;
} VBSVGA3dCmdDXDefineVideoDecoder;

typedef struct {
   uint32_t videoDecoderId;
   uint32_t videoDecoderOutputViewId;
} VBSVGA3dCmdDXVideoDecoderBeginFrame;

typedef struct {
   SVGA3dSurfaceId sidBuffer;
   uint32_t bufferType;
   uint32_t dataOffset;
   uint32_t dataSize;
   uint32_t firstMBaddress;
   uint32_t numMBsInBuffer;
} VBSVGA3dVideoDecoderBufferDesc;

typedef struct {
   uint32_t videoDecoderId;
} VBSVGA3dCmdDXVideoDecoderSubmitBuffers;

typedef struct {
   uint32_t videoDecoderId;
} VBSVGA3dCmdDXVideoDecoderEndFrame;

typedef struct {
   uint32_t videoDecoderId;
} VBSVGA3dCmdDXDestroyVideoDecoder;

typedef struct {
   uint32_t videoDecoderOutputViewId;
} VBSVGA3dCmdDXDestroyVideoDecoderOutputView;

typedef struct __attribute__((packed)) {
   VBSVGA3dGuid DecodeProfile;
   uint8_t fAYUV;
   uint8_t fNV12;
   uint8_t fYUY2;
} VBSVGA3dDecodeProfileInfo;

typedef struct {
   VBSVGA3dVideoDecoderDesc desc;
   VBSVGA3dVideoDecoderConfig aConfig[1];
} VBSVGA3dDecodeConfigInfo;

typedef struct {
   uint64_t fenceValue;
   uint32_t cbDataOut;
   union {
      VBSVGA3dDecodeProfileInfo aDecodeProfile[1];
      VBSVGA3dDecodeConfigInfo config;
   } data;
} VBSVGA3dVideoCapabilityMobLayout;

typedef struct {
   uint32_t capability;
   uint32_t mobid;
   uint32_t offsetInBytes;
   uint32_t sizeInBytes;
   uint64_t fenceValue;
} VBSVGA3dCmdDXGetVideoCapability;

#endif
