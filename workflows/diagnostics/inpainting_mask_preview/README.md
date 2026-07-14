# Inpainting Mask Preview Diagnostic Workflow

**Status:** Diagnostic only (Package 4.3)

## Purpose

Visualize a mask and optional source/mask overlay without running diffusion.

## Nodes

- `LoadImage` — source image
- `LoadImageMask` — mask (`red` channel, `white` = masked)
- `MaskToImage` — visible mask preview
- `SaveImage` — `ai_studio_diag_mask_preview`
- `ImageBlend` — source/mask overlay
- `SaveImage` — `ai_studio_diag_mask_overlay`

No checkpoint or sampler nodes are used.
