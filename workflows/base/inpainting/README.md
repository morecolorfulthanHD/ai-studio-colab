# inpainting

**Status:** Implemented (Production Package 4)

## Purpose

Regenerate a masked region of an image while preserving unmasked areas.

## Required Models

| Model | Location |
|-------|----------|
| SD 1.5 inpainting checkpoint | Drive: `AI_Studio/models/shared/checkpoints/512-inpainting-ema.safetensors` |

Uses `VAEEncodeForInpaint` with the dedicated SD1.5 inpainting checkpoint (`512-inpainting-ema.safetensors`). This is the **true-inpainting** base path, so KSampler denoise is **1.0** (full denoise on the masked latent). Lower-strength masked editing without full latent replacement will be a separate future workflow.

## Required Nodes

None beyond stock ComfyUI.

## Graph (9 nodes)

`LoadImage` + `LoadImageMask` → `VAEEncodeForInpaint` → `KSampler` ← dual `CLIPTextEncode` ← `CheckpointLoaderSimple` → `VAEDecode` → `SaveImage`

## Defaults

| Parameter | Value |
|-----------|-------|
| Checkpoint | `512-inpainting-ema.safetensors` |
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

- Dedicated inpainting checkpoint must be present in Drive; no automatic download is performed.
- SD1.5 inpainting can still show seams at mask boundaries; smaller masks help.
