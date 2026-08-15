#!/usr/bin/env python3
"""Teach Linux vmwgfx to validate and forward VirtualBox video commands."""

from __future__ import annotations

import shutil
import sys
import re
from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"{label} did not match Linux 7.1.5")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


if len(sys.argv) != 3:
    raise SystemExit("usage: apply_vmsvga_video.py LINUX_SOURCE PATCH_SOURCE")

linux = Path(sys.argv[1]).resolve()
patch = Path(sys.argv[2]).resolve()
vmw = linux / "drivers/gpu/drm/vmwgfx"
device = vmw / "device_include"
shutil.copy2(patch / "vbox_vmsvga_video.h", device / "vbox_vmsvga_video.h")

types = device / "svga3d_types.h"
replace_once(
    types,
    """\tSVGA_COTABLE_UAVIEW = 11,
\tSVGA_COTABLE_MAX = 12,
} SVGACOTableType;""",
    """\tSVGA_COTABLE_UAVIEW = 11,
\t/*
\t * VirtualBox video tables use wire identifiers 100..104.  Keep compact
\t * internal indices so the context's table array remains bounded.
\t */
\tSVGA_COTABLE_VBOX_VIDEO_PROCESSOR = 12,
\tSVGA_COTABLE_VBOX_VIDEO_DECODER_OUTPUT_VIEW = 13,
\tSVGA_COTABLE_VBOX_VIDEO_DECODER = 14,
\tSVGA_COTABLE_VBOX_VIDEO_PROCESSOR_INPUT_VIEW = 15,
\tSVGA_COTABLE_VBOX_VIDEO_PROCESSOR_OUTPUT_VIEW = 16,
\tSVGA_COTABLE_MAX = 17,
} SVGACOTableType;""",
    "vmwgfx COTable type extension",
)

drv = vmw / "vmwgfx_drv.h"
replace_once(
    drv,
    """#include <linux/hashtable.h>

#include <drm/drm_auth.h>""",
    """#include <linux/hashtable.h>
#include <linux/pci.h>

#include <drm/drm_auth.h>""",
    "vmwgfx PCI identity include",
)
replace_once(
    drv,
    """static inline bool has_sm5_context(const struct vmw_private *dev_priv)
{
\treturn (dev_priv->sm_type >= VMW_SM_5);
}
""",
    """static inline bool has_sm5_context(const struct vmw_private *dev_priv)
{
\treturn (dev_priv->sm_type >= VMW_SM_5);
}

/**
 * has_vbox_video - Does this VMSVGA device expose VirtualBox video commands.
 */
static inline bool has_vbox_video(const struct vmw_private *dev_priv)
{
\tstruct pci_dev *pdev = to_pci_dev(dev_priv->drm.dev);

\t/*
\t * VirtualBox exposes its extended D3D11 video command range only when the
\t * emulated adapter has the VBox PCI identity. T1OS deliberately binds
\t * vmwgfx to that identity while retaining the VMSVGA BAR layout.
\t */
\treturn pdev->vendor == 0x80ee && pdev->device == 0xbeef &&
\t       dev_priv->has_mob && dev_priv->devcaps &&
\t       (dev_priv->devcaps[SVGA3D_DEVCAP_3D] & 0x00000001U);
}

static inline u32 vmw_context_cotable_max(const struct vmw_private *dev_priv)
{
\tif (has_vbox_video(dev_priv))
\t\treturn SVGA_COTABLE_MAX;
\treturn has_sm5_context(dev_priv) ? SVGA_COTABLE_MAX :
\t\tSVGA_COTABLE_DX10_MAX;
}
""",
    "vmwgfx VirtualBox video capability helper",
)

vmwgfx_driver = vmw / "vmwgfx_drv.c"
replace_once(
    vmwgfx_driver,
    """static const struct pci_device_id vmw_pci_id_list[] = {
\t{ PCI_DEVICE(PCI_VENDOR_ID_VMWARE, VMWGFX_PCI_ID_SVGA2) },
\t{ PCI_DEVICE(PCI_VENDOR_ID_VMWARE, VMWGFX_PCI_ID_SVGA3) },
\t{ }
};""",
    """static const struct pci_device_id vmw_pci_id_list[] = {
\t{ PCI_DEVICE(PCI_VENDOR_ID_VMWARE, VMWGFX_PCI_ID_SVGA2),
\t  .driver_data = VMWGFX_PCI_ID_SVGA2 },
\t{ PCI_DEVICE(PCI_VENDOR_ID_VMWARE, VMWGFX_PCI_ID_SVGA3),
\t  .driver_data = VMWGFX_PCI_ID_SVGA3 },
\t/*
\t * VBox video extensions use the VBoxSVGA PCI identity while T1OS keeps
\t * the VMSVGA/SVGA2 BAR layout through the host CFGM overlay.
\t */
\t{ PCI_DEVICE(0x80ee, 0xbeef),
\t  .driver_data = VMWGFX_PCI_ID_SVGA2 },
\t{ }
};""",
    "vmwgfx VirtualBox extension PCI identity",
)
replace_once(
    vmwgfx_driver,
    """\tret = vmw_driver_load(vmw, ent->device);
\tif (ret)""",
    """\tret = vmw_driver_load(vmw, (u32)ent->driver_data);
\tif (ret)""",
    "vmwgfx transport PCI identity",
)

context = vmw / "vmwgfx_context.c"
text = context.read_text(encoding="utf-8")
text, count = re.subn(
    r"has_sm5_context\(dev_priv\) \?\s*"
    r"SVGA_COTABLE_MAX : SVGA_COTABLE_DX10_MAX",
    "vmw_context_cotable_max(dev_priv)",
    text,
)
if count != 2:
    raise SystemExit("vmwgfx device COTable limits did not match Linux 7.1.5")
text, count = re.subn(
    r"has_sm5_context\(ctx->dev_priv\) \?\s*"
    r"SVGA_COTABLE_MAX : SVGA_COTABLE_DX10_MAX",
    "vmw_context_cotable_max(ctx->dev_priv)",
    text,
)
if count != 2:
    raise SystemExit("vmwgfx context COTable limits did not match Linux 7.1.5")
context.write_text(text, encoding="utf-8")

cotable = vmw / "vmwgfx_cotable.c"
replace_once(
    cotable,
    """\t{1, sizeof(SVGACOTableDXShaderEntry), &vmw_dx_shader_cotable_list_scrub},
\t{1, sizeof(SVGACOTableDXUAViewEntry), &vmw_view_cotable_list_destroy}
};""",
    """\t{1, sizeof(SVGACOTableDXShaderEntry), &vmw_dx_shader_cotable_list_scrub},
\t{1, sizeof(SVGACOTableDXUAViewEntry), &vmw_view_cotable_list_destroy},
\t{1, 16384, NULL}, /* VBSVGACOTableDXVideoProcessorEntry */
\t{1, 64, NULL},    /* VBSVGACOTableDXVideoDecoderOutputViewEntry */
\t{1, 256, NULL},   /* VBSVGACOTableDXVideoDecoderEntry */
\t{1, 128, NULL},   /* VBSVGACOTableDXVideoProcessorInputViewEntry */
\t{1, 128, NULL},   /* VBSVGACOTableDXVideoProcessorOutputViewEntry */
};""",
    "vmwgfx VirtualBox video COTable descriptions",
)
replace_once(
    cotable,
    """\tSVGA_COTABLE_DXQUERY,
\tSVGA_COTABLE_UAVIEW,
};""",
    """\tSVGA_COTABLE_DXQUERY,
\tSVGA_COTABLE_UAVIEW,
\tSVGA_COTABLE_VBOX_VIDEO_DECODER,
\tSVGA_COTABLE_VBOX_VIDEO_DECODER_OUTPUT_VIEW,
\tSVGA_COTABLE_VBOX_VIDEO_PROCESSOR_INPUT_VIEW,
\tSVGA_COTABLE_VBOX_VIDEO_PROCESSOR_OUTPUT_VIEW,
\tSVGA_COTABLE_VBOX_VIDEO_PROCESSOR,
};""",
    "vmwgfx VirtualBox video COTable scrub order",
)
replace_once(
    cotable,
    """static int vmw_cotable_bind(struct vmw_resource *res,
\t\t\t    struct ttm_validate_buffer *val_buf);""",
    """static u32 vmw_cotable_wire_type(SVGACOTableType type)
{
\tif (type >= SVGA_COTABLE_VBOX_VIDEO_PROCESSOR)
\t\treturn 100 + type - SVGA_COTABLE_VBOX_VIDEO_PROCESSOR;
\treturn type;
}

static int vmw_cotable_bind(struct vmw_resource *res,
\t\t\t    struct ttm_validate_buffer *val_buf);""",
    "vmwgfx COTable wire-type mapper",
)
text = cotable.read_text(encoding="utf-8")
if text.count("cmd->body.type = vcotbl->type;") != 2:
    raise SystemExit("vmwgfx COTable command types did not match Linux 7.1.5")
text = text.replace(
    "cmd->body.type = vcotbl->type;",
    "cmd->body.type = vmw_cotable_wire_type(vcotbl->type);",
)
if text.count("cmd0->body.type = vcotbl->type;") != 1:
    raise SystemExit("vmwgfx COTable readback type did not match Linux 7.1.5")
text = text.replace(
    "cmd0->body.type = vcotbl->type;",
    "cmd0->body.type = vmw_cotable_wire_type(vcotbl->type);",
)
if text.count("cmd1->body.type = vcotbl->type;") != 1:
    raise SystemExit("vmwgfx COTable scrub type did not match Linux 7.1.5")
cotable.write_text(
    text.replace(
        "cmd1->body.type = vcotbl->type;",
        "cmd1->body.type = vmw_cotable_wire_type(vcotbl->type);",
    ),
    encoding="utf-8",
)

execbuf = vmw / "vmwgfx_execbuf.c"
replace_once(
    execbuf,
    """#include "vmwgfx_so.h"

#include <drm/ttm/ttm_bo.h>""",
    """#include "vmwgfx_so.h"
#include "device_include/vbox_vmsvga_video.h"

#include <drm/ttm/ttm_bo.h>""",
    "vmwgfx video ABI include",
)
replace_once(
    execbuf,
    """\tu32 cotable_max = has_sm5_context(ctx->dev_priv) ?
\t\tSVGA_COTABLE_MAX : SVGA_COTABLE_DX10_MAX;""",
    """\tu32 cotable_max = vmw_context_cotable_max(ctx->dev_priv);""",
    "vmwgfx validation COTable limit",
)

verifier = r'''
static int
vmw_vbox_video_notify(struct vmw_sw_context *sw_context,
		      SVGACOTableType type, u32 id, u32 limit)
{
	struct vmw_ctx_validation_info *ctx_node = VMW_GET_CTX_NODE(sw_context);
	struct vmw_resource *table;

	if (!ctx_node || id >= limit)
		return -EINVAL;

	table = vmw_context_cotable(ctx_node->ctx, type);
	if (IS_ERR_OR_NULL(table))
		return table ? PTR_ERR(table) : -EINVAL;

	return vmw_cotable_notify(table, id);
}

static int
vmw_cmd_check_vbox_video(struct vmw_private *dev_priv,
			 struct vmw_sw_context *sw_context,
			 SVGA3dCmdHeader *header)
{
	void *body = header + 1;
	int ret;
	u32 count;
	u32 i;

	if (!has_vbox_video(dev_priv) || !sw_context->dx_ctx_node)
		return -EINVAL;

	switch (header->id) {
	case VBSVGA_3D_CMD_DX_DEFINE_VIDEO_DECODER_OUTPUT_VIEW: {
		struct vbsvga3d_define_decoder_output_view *cmd = body;

		if (header->size != sizeof(*cmd) ||
		    cmd->view_id >= VBSVGA_VIDEO_MAX_DECODER_OUTPUT_VIEWS ||
		    cmd->sid == SVGA3D_INVALID_ID)
			return -EINVAL;

		ret = vmw_cmd_res_check(dev_priv, sw_context, vmw_res_surface,
					VMW_RES_DIRTY_SET, user_surface_converter,
					&cmd->sid, NULL);
		if (ret)
			return ret;

		return vmw_vbox_video_notify(
			sw_context,
			SVGA_COTABLE_VBOX_VIDEO_DECODER_OUTPUT_VIEW,
			cmd->view_id, VBSVGA_VIDEO_MAX_DECODER_OUTPUT_VIEWS);
	}
	case VBSVGA_3D_CMD_DX_DEFINE_VIDEO_DECODER: {
		struct vbsvga3d_define_decoder *cmd = body;

		if (header->size != sizeof(*cmd))
			return -EINVAL;
		return vmw_vbox_video_notify(
			sw_context, SVGA_COTABLE_VBOX_VIDEO_DECODER,
			cmd->decoder_id, VBSVGA_VIDEO_MAX_DECODERS);
	}
	case VBSVGA_3D_CMD_DX_VIDEO_DECODER_BEGIN_FRAME: {
		struct vbsvga3d_decoder_begin_frame *cmd = body;

		if (header->size != sizeof(*cmd) ||
		    cmd->decoder_id >= VBSVGA_VIDEO_MAX_DECODERS ||
		    cmd->view_id >= VBSVGA_VIDEO_MAX_DECODER_OUTPUT_VIEWS)
			return -EINVAL;
		return 0;
	}
	case VBSVGA_3D_CMD_DX_VIDEO_DECODER_SUBMIT_BUFFERS: {
		struct vbsvga3d_decoder_submit *cmd = body;
		size_t descriptor_bytes;

		if (header->size < sizeof(*cmd) ||
		    cmd->decoder_id >= VBSVGA_VIDEO_MAX_DECODERS)
			return -EINVAL;

		descriptor_bytes = header->size - sizeof(*cmd);
		if (descriptor_bytes % sizeof(cmd->buffers[0]))
			return -EINVAL;
		count = descriptor_bytes / sizeof(cmd->buffers[0]);
		if (!count || count > VBSVGA_VIDEO_MAX_SUBMIT_BUFFERS)
			return -EINVAL;

		for (i = 0; i < count; ++i) {
			struct vbsvga3d_decoder_buffer_desc *desc =
				&cmd->buffers[i];

			if (desc->sid == SVGA3D_INVALID_ID ||
			    desc->data_offset + desc->data_size <
			    desc->data_offset)
				return -EINVAL;
			ret = vmw_cmd_res_check(
				dev_priv, sw_context, vmw_res_surface,
				VMW_RES_DIRTY_NONE, user_surface_converter,
				&desc->sid, NULL);
			if (ret)
				return ret;
		}
		return 0;
	}
	case VBSVGA_3D_CMD_DX_VIDEO_DECODER_END_FRAME:
	case VBSVGA_3D_CMD_DX_DESTROY_VIDEO_DECODER: {
		struct vbsvga3d_decoder_id *cmd = body;

		return header->size == sizeof(*cmd) &&
		       cmd->decoder_id < VBSVGA_VIDEO_MAX_DECODERS ?
		       0 : -EINVAL;
	}
	case VBSVGA_3D_CMD_DX_DESTROY_VIDEO_DECODER_OUTPUT_VIEW: {
		struct vbsvga3d_decoder_view_id *cmd = body;

		return header->size == sizeof(*cmd) &&
		       cmd->view_id < VBSVGA_VIDEO_MAX_DECODER_OUTPUT_VIEWS ?
		       0 : -EINVAL;
	}
	case VBSVGA_3D_CMD_DX_GET_VIDEO_CAPABILITY: {
		struct vbsvga3d_get_video_capability *cmd = body;
		struct vmw_bo *vmw_bo;

		if (header->size != sizeof(*cmd) ||
		    cmd->capability > 2 ||
		    cmd->size_in_bytes < sizeof(u64) + sizeof(u32) ||
		    cmd->offset_in_bytes + cmd->size_in_bytes <
		    cmd->offset_in_bytes)
			return -EINVAL;

		ret = vmw_translate_mob_ptr(
			dev_priv, sw_context, &cmd->mobid, &vmw_bo);
		if (ret)
			return ret;

		return cmd->offset_in_bytes + cmd->size_in_bytes <=
		       vmw_bo->tbo.base.size ? 0 : -EINVAL;
	}
	default:
		return -EINVAL;
	}
}

'''
anchor = "bool vmw_cmd_describe(const void *buf, u32 *size, char const **cmd)\n"
text = execbuf.read_text(encoding="utf-8")
if text.count(anchor) != 1:
    raise SystemExit("vmwgfx command-description anchor did not match Linux 7.1.5")
text = text.replace(anchor, verifier + anchor, 1)
old = """\t*size = header->size + sizeof(SVGA3dCmdHeader);

\tcmd_id -= SVGA_3D_CMD_BASE;
\tif (unlikely(*size > size_remaining))
\t\tgoto out_invalid;
"""
new = """\t*size = header->size + sizeof(SVGA3dCmdHeader);
\tif (unlikely(*size > size_remaining))
\t\tgoto out_invalid;

\tif (cmd_id >= VBSVGA_3D_CMD_BASE && cmd_id < VBSVGA_3D_CMD_MAX) {
\t\tret = vmw_cmd_check_vbox_video(dev_priv, sw_context, header);
\t\tif (ret)
\t\t\tdrm_warn(&dev_priv->drm,
\t\t\t\t "T1OS VMSVGA video command %u size %u rejected: %d\\n",
\t\t\t\t cmd_id, header->size, ret);
\t\treturn ret;
\t}

\tcmd_id -= SVGA_3D_CMD_BASE;
"""
if text.count(old) != 1:
    raise SystemExit("vmwgfx command range verifier did not match Linux 7.1.5")
text = text.replace(old, new, 1)

diagnostic_replacements = [
    (
        """\tret = vmw_execbuf_tie_context(dev_priv, sw_context, dx_context_handle);
\tif (unlikely(ret != 0))
\t\tgoto out_err_nores;
""",
        """\tret = vmw_execbuf_tie_context(dev_priv, sw_context, dx_context_handle);
\tif (unlikely(ret != 0)) {
\t\tdrm_warn(&dev_priv->drm,
\t\t\t "T1OS VMSVGA execbuf context lookup failed: %d\\n", ret);
\t\tgoto out_err_nores;
\t}
""",
    ),
    (
        """\t\tret = vmw_cmd_check(dev_priv, sw_context, buf, &size);
\t\tif (unlikely(ret != 0))
\t\t\treturn ret;
""",
        """\t\tret = vmw_cmd_check(dev_priv, sw_context, buf, &size);
\t\tif (unlikely(ret != 0)) {
\t\t\tdrm_warn(&dev_priv->drm,
\t\t\t\t "T1OS VMSVGA execbuf command %u at offset %u "
\t\t\t\t "failed validation: %d\\n",
\t\t\t\t ((u32 *)buf)[0],
\t\t\t\t sw_context->buf_start ?
\t\t\t\t (u32)((char *)buf -
\t\t\t\t       (char *)sw_context->buf_start) : 0,
\t\t\t\t ret);
\t\t\treturn ret;
\t\t}
""",
    ),
    (
        """\tret = vmw_cmd_check_all(dev_priv, sw_context, kernel_commands,
\t\t\t\tcommand_size);
\tif (unlikely(ret != 0))
\t\tgoto out_err_nores;
""",
        """\tret = vmw_cmd_check_all(dev_priv, sw_context, kernel_commands,
\t\t\t\tcommand_size);
\tif (unlikely(ret != 0)) {
\t\tdrm_warn(&dev_priv->drm,
\t\t\t "T1OS VMSVGA execbuf command validation failed: %d\\n", ret);
\t\tgoto out_err_nores;
\t}
""",
    ),
    (
        """\tret = vmw_resources_reserve(sw_context);
\tif (unlikely(ret != 0))
\t\tgoto out_err_nores;
""",
        """\tret = vmw_resources_reserve(sw_context);
\tif (unlikely(ret != 0)) {
\t\tdrm_warn(&dev_priv->drm,
\t\t\t "T1OS VMSVGA execbuf resource reserve failed: %d\\n", ret);
\t\tgoto out_err_nores;
\t}
""",
    ),
    (
        """\tret = vmw_validation_bo_reserve(&val_ctx, true);
\tif (unlikely(ret != 0))
\t\tgoto out_err_nores;
""",
        """\tret = vmw_validation_bo_reserve(&val_ctx, true);
\tif (unlikely(ret != 0)) {
\t\tdrm_warn(&dev_priv->drm,
\t\t\t "T1OS VMSVGA execbuf buffer reserve failed: %d\\n", ret);
\t\tgoto out_err_nores;
\t}
""",
    ),
    (
        """\tret = vmw_validation_bo_validate(&val_ctx, true);
\tif (unlikely(ret != 0))
\t\tgoto out_err;
""",
        """\tret = vmw_validation_bo_validate(&val_ctx, true);
\tif (unlikely(ret != 0)) {
\t\tdrm_warn(&dev_priv->drm,
\t\t\t "T1OS VMSVGA execbuf buffer validate failed: %d\\n", ret);
\t\tgoto out_err;
\t}
""",
    ),
    (
        """\tret = vmw_validation_res_validate(&val_ctx, true);
\tif (unlikely(ret != 0))
\t\tgoto out_err;
""",
        """\tret = vmw_validation_res_validate(&val_ctx, true);
\tif (unlikely(ret != 0)) {
\t\tdrm_warn(&dev_priv->drm,
\t\t\t "T1OS VMSVGA execbuf resource validate failed: %d\\n", ret);
\t\tgoto out_err;
\t}
""",
    ),
    (
        """\t\tret = vmw_rebind_contexts(sw_context);
\t\tif (unlikely(ret != 0))
\t\t\tgoto out_unlock_binding;
""",
        """\t\tret = vmw_rebind_contexts(sw_context);
\t\tif (unlikely(ret != 0)) {
\t\t\tdrm_warn(&dev_priv->drm,
\t\t\t\t "T1OS VMSVGA execbuf context rebind failed: %d\\n", ret);
\t\t\tgoto out_unlock_binding;
\t\t}
""",
    ),
    (
        """\tmutex_unlock(&dev_priv->binding_mutex);
\tif (ret)
\t\tgoto out_err;
""",
        """\tmutex_unlock(&dev_priv->binding_mutex);
\tif (ret) {
\t\tdrm_warn(&dev_priv->drm,
\t\t\t "T1OS VMSVGA execbuf submission failed: %d\\n", ret);
\t\tgoto out_err;
\t}
""",
    ),
]
for before, after in diagnostic_replacements:
    if text.count(before) != 1:
        raise SystemExit("vmwgfx execbuf diagnostic anchor did not match Linux 7.1.5")
    text = text.replace(before, after, 1)

execbuf.write_text(text, encoding="utf-8")
