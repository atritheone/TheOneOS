#!/usr/bin/env python3
"""Verify the pinned NVIDIA exporter preserves natural per-plane layouts."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit(
            "usage: apply_t1os_planar_export.py <nvidia-vaapi-driver-source>"
        )

    source = Path(sys.argv[1]).resolve()
    path = source / "src" / "direct" / "direct-export-buf.c"
    text = path.read_text(encoding="utf-8")

    # Migrate build caches produced by the superseded shared-modifier patch.
    # A fresh pinned source tree already has the natural form and is unchanged.
    legacy_layout = """    // Chromium represents one multi-planar NativePixmap with one DRM modifier.
    // Keep a distinct dma-buf object for each plane (so every plane begins at offset
    // zero), but calculate both objects with the largest plane block height. This
    // preserves the one-modifier contract while avoiding the non-zero tiled chroma
    // offset that NVIDIA EGL rejects when Chromium imports the planes separately.
    calculate_unified_image_layout(&drv->driverContext, driverImages, surface->width, surface->height,
                                   fmtInfo->bppc, fmtInfo->numPlanes, fmtInfo->plane, true);
"""
    natural_layout = """    // Reuse the layout purely to obtain each plane's block height and pitch/aligned
    // size; the packed offsets it returns are ignored (each plane is offset 0 in its
    // own buffer). Pass unifyBlockHeight=false: each plane is its own dma-buf object
    // with its own modifier, so it keeps its natural per-plane block height and
    // matches what the decoder produced (see calculate_unified_image_layout).
    calculate_unified_image_layout(&drv->driverContext, driverImages, surface->width, surface->height,
                                   fmtInfo->bppc, fmtInfo->numPlanes, fmtInfo->plane, false);
"""
    legacy_mapping = """        // CUDA derives block-linear tiling from the mapped array height. Map the
        // aligned height used to calculate the shared modifier, while copying only the
        // natural visible rows below. The advertised modifier and actual allocation then
        // describe the same tiling for both luma and chroma objects.
        const uint32_t alignedHeight = driverImages[i].pitch != 0 ?
            driverImages[i].memorySize / driverImages[i].pitch : driverImages[i].height;
        CUDA_EXTERNAL_MEMORY_MIPMAPPED_ARRAY_DESC mipmapArrayDesc = {
            .arrayDesc = {
                .Width = driverImages[i].width,
                .Height = alignedHeight,
"""
    natural_mapping = """        // Create the array at the plane's natural height. Each plane is its own object
        // carrying its own modifier, and calculate_unified_image_layout (called with
        // unifyBlockHeight=false) already advertised each plane's per-plane block height.
        // Handing CUDA the natural height makes it derive that same per-plane block, so
        // the array tiling matches the modifier. (Rounding up to the shared max block --
        // as the single-buffer path must -- would instead make CUDA pick the larger block
        // and disagree with the per-plane modifier -> the importer detiles wrong -> green
        // chroma, e.g. NV12 chroma at a 256x144 coded height.)
        CUDA_EXTERNAL_MEMORY_MIPMAPPED_ARRAY_DESC mipmapArrayDesc = {
            .arrayDesc = {
                .Width = driverImages[i].width,
                .Height = driverImages[i].height,
"""
    migrated = False
    if legacy_layout in text:
        text = text.replace(legacy_layout, natural_layout, 1)
        migrated = True
    if legacy_mapping in text:
        text = text.replace(legacy_mapping, natural_mapping, 1)
        migrated = True
    if migrated:
        path.write_text(text, encoding="utf-8")

    required = (
        "fmtInfo->bppc, fmtInfo->numPlanes, fmtInfo->plane, false);",
        ".Height = driverImages[i].height,",
        "backingImage->mods[i] = driverImages[i].mods;",
        "desc->objects[i].drm_format_modifier = img->mods[i];",
    )
    missing = [anchor for anchor in required if anchor not in text]
    if missing:
        raise RuntimeError(
            "The pinned exporter no longer preserves natural per-plane "
            f"modifiers: {missing}"
        )

    # Chromium now transports each object's modifier independently. Rewriting
    # these layouts to one synthetic modifier makes NVIDIA EGL reject or
    # mis-detile the standalone luma/chroma objects.
    action = "Restored and verified" if migrated else "Verified"
    print(f"{action} T1OS NVIDIA natural per-plane DMA-BUF export.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
