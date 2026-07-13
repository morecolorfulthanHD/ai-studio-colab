# inpainting

**Status:** Implemented (Production Package 4)

## Purpose

Regenerate a masked region of an image while preserving unmasked areas.

## Required Models

| Model | Location |
|-------|----------|
| SD 1.5 checkpoint | Drive: `AI_Studio/models/shared/checkpoints/sd15.safetensors` |

Uses `VAEEncodeForInpaint` with the standard SD1.5 checkpoint. This is the **true-inpainting** base path, so KSampler denoise is **1.0** (full denoise on the masked latent). Lower-strength masked editing without full latent replacement will be a separate future workflow.

## Required Nodes

None beyond stock ComfyUI.

## Graph (9 nodes)

`LoadImage` + `LoadImageMask` → `VAEEncodeForInpaint` → `KSampler` ← dual `CLIPTextEncode` ← `CheckpointLoaderSimple` → `VAEDecode` → `SaveImage`

## Defaults

| Parameter | Value |
|-----------|-------|
| Checkpoint | `sd15.safetensors` |
| Denoise | **1.0** (true-inpainting path via `VAEEncodeForInpaint`) |
| Steps | 24 |
| CFG | 7.0 |
| Output prefix | `ai_studio_base_inpainting` |

## Inputs

- Source image (`AI_Studio/inputs/images/`)
- Mask image — white = regenerate, black = preserve (`AI_Studio/inputs/masks/`)

## Preparation

```bash
python core/scripts/prepare_workflow.py --workflow inpainting --input /path/to/source.png --mask /path/to/mask.png
```

## Known Limitations

- SD1.5 base checkpoint inpainting may show seams at mask boundaries; smaller masks and moderate denoise help.
- Dedicated inpainting checkpoints are not required in this package but may improve blending in future workflows.
