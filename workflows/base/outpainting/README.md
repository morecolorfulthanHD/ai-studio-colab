# outpainting

**Status:** Implemented (Production Package 4)

## Purpose

Extend the canvas beyond original image boundaries using `ImagePadForOutpaint` and mask-aware inpainting.

## Required Models

| Model | Location |
|-------|----------|
| SD 1.5 checkpoint | Drive: `AI_Studio/models/shared/checkpoints/sd15.safetensors` |

## Required Nodes

None beyond stock ComfyUI.

## Graph (9 nodes)

`LoadImage` → `ImagePadForOutpaint` → `VAEEncodeForInpaint` → `KSampler` ← dual `CLIPTextEncode` ← `CheckpointLoaderSimple` → `VAEDecode` → `SaveImage`

## Defaults

| Parameter | Value |
|-----------|-------|
| Expansion | left=256, right=0, top=256, bottom=0 (configurable per side) |
| Denoise | **1.0** (true-inpainting path via `VAEEncodeForInpaint`) |
| Steps | 24 |
| CFG | 7.0 |
| Output prefix | `ai_studio_base_outpainting` |

## Preparation

```bash
python core/scripts/prepare_workflow.py --workflow outpainting --input /path/to/source.png --left 256 --right 256
```

Uses `ImagePadForOutpaint` → `VAEEncodeForInpaint` → `KSampler`. This is the same true-inpainting latent path as base inpainting, so KSampler denoise is **1.0**. Lower-strength outpainting would require a separate future latent-mask workflow.

## Known Limitations (SD1.5 base outpainting)

- Large single-step expansions often produce visible seams or perspective drift.
- **Iterative small expansions (128–256 px per side)** generally work better than one large pad.
- Scene continuity depends heavily on prompt quality; no ControlNet or reference lock in this package.
- SD1.5 does not reliably preserve fine detail at expanded edges without downstream identity or scene-consistency workflows.
