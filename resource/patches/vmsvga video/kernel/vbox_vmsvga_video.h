/* SPDX-License-Identifier: GPL-2.0 OR MIT */
/*
 * VirtualBox VMSVGA video command ABI.  These commands extend the VMware
 * SVGA3D stream and are implemented by VirtualBox's host 3D service.
 */

#ifndef _VBOX_VMSVGA_VIDEO_H_
#define _VBOX_VMSVGA_VIDEO_H_

#define VBSVGA3D_CAP_VIDEO					0x00000002U

#define VBSVGA_3D_CMD_BASE					1000000U
#define VBSVGA_3D_CMD_DX_DEFINE_VIDEO_PROCESSOR		(VBSVGA_3D_CMD_BASE + 0)
#define VBSVGA_3D_CMD_DX_DEFINE_VIDEO_DECODER_OUTPUT_VIEW	(VBSVGA_3D_CMD_BASE + 1)
#define VBSVGA_3D_CMD_DX_DEFINE_VIDEO_DECODER			(VBSVGA_3D_CMD_BASE + 2)
#define VBSVGA_3D_CMD_DX_VIDEO_DECODER_BEGIN_FRAME		(VBSVGA_3D_CMD_BASE + 3)
#define VBSVGA_3D_CMD_DX_VIDEO_DECODER_SUBMIT_BUFFERS		(VBSVGA_3D_CMD_BASE + 4)
#define VBSVGA_3D_CMD_DX_VIDEO_DECODER_END_FRAME		(VBSVGA_3D_CMD_BASE + 5)
#define VBSVGA_3D_CMD_DX_DESTROY_VIDEO_DECODER			(VBSVGA_3D_CMD_BASE + 9)
#define VBSVGA_3D_CMD_DX_DESTROY_VIDEO_DECODER_OUTPUT_VIEW	(VBSVGA_3D_CMD_BASE + 10)
#define VBSVGA_3D_CMD_DX_GET_VIDEO_CAPABILITY			(VBSVGA_3D_CMD_BASE + 33)
#define VBSVGA_3D_CMD_MAX					(VBSVGA_3D_CMD_BASE + 34)

#define VBSVGA_COTABLE_VIDEO_PROCESSOR				100U
#define VBSVGA_COTABLE_VIDEO_DECODER_OUTPUT_VIEW		101U
#define VBSVGA_COTABLE_VIDEO_DECODER				102U
#define VBSVGA_COTABLE_VIDEO_PROCESSOR_INPUT_VIEW		103U
#define VBSVGA_COTABLE_VIDEO_PROCESSOR_OUTPUT_VIEW		104U

#define VBSVGA_VIDEO_MAX_DECODERS				128U
#define VBSVGA_VIDEO_MAX_DECODER_OUTPUT_VIEWS			128U
#define VBSVGA_VIDEO_MAX_SUBMIT_BUFFERS				32U

struct vbsvga3d_guid {
	u32 data1;
	u16 data2;
	u16 data3;
	u8 data4[8];
};

struct vbsvga3d_vdov_desc {
	struct vbsvga3d_guid decode_profile;
	u32 view_dimension;
	u32 dimension[4];
};

struct vbsvga3d_video_decoder_desc {
	struct vbsvga3d_guid decode_profile;
	u32 sample_width;
	u32 sample_height;
	u32 output_format;
};

struct vbsvga3d_video_decoder_config {
	struct vbsvga3d_guid bitstream_encryption;
	struct vbsvga3d_guid mbcontrol_encryption;
	struct vbsvga3d_guid resid_diff_encryption;
	u32 values[12];
	u16 min_render_target_count;
	u16 decoder_specific;
};

struct vbsvga3d_define_decoder_output_view {
	u32 view_id;
	u32 sid;
	struct vbsvga3d_vdov_desc desc;
};

struct vbsvga3d_define_decoder {
	u32 decoder_id;
	struct vbsvga3d_video_decoder_desc desc;
	struct vbsvga3d_video_decoder_config config;
};

struct vbsvga3d_decoder_begin_frame {
	u32 decoder_id;
	u32 view_id;
};

struct vbsvga3d_decoder_buffer_desc {
	u32 sid;
	u32 buffer_type;
	u32 data_offset;
	u32 data_size;
	u32 first_mb_address;
	u32 num_mbs;
};

struct vbsvga3d_decoder_submit {
	u32 decoder_id;
	struct vbsvga3d_decoder_buffer_desc buffers[];
};

struct vbsvga3d_decoder_id {
	u32 decoder_id;
};

struct vbsvga3d_decoder_view_id {
	u32 view_id;
};

struct vbsvga3d_get_video_capability {
	u32 capability;
	u32 mobid;
	u32 offset_in_bytes;
	u32 size_in_bytes;
	u64 fence_value;
};

static_assert(sizeof(struct vbsvga3d_guid) == 16);
static_assert(sizeof(struct vbsvga3d_vdov_desc) == 36);
static_assert(sizeof(struct vbsvga3d_video_decoder_desc) == 28);
static_assert(sizeof(struct vbsvga3d_video_decoder_config) == 100);
static_assert(sizeof(struct vbsvga3d_define_decoder_output_view) == 44);
static_assert(sizeof(struct vbsvga3d_define_decoder) == 132);
static_assert(sizeof(struct vbsvga3d_decoder_begin_frame) == 8);
static_assert(sizeof(struct vbsvga3d_decoder_buffer_desc) == 24);
static_assert(sizeof(struct vbsvga3d_get_video_capability) == 24);

#endif
