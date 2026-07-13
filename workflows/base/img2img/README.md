# img2img

**Status:** Implemented (Production Package 4)

## Purpose

Transform an existing image while preserving overall composition. Denoise strength controls how much of the source latent is retained.

## Required Models

| Model | Location |
|-------|----------|
| SD 1.5 checkpoint | Drive: `AI_Studio/models/shared/checkpoints/sd15.safetensors` |

## Required Nodes

None beyond stock ComfyUI.

## Graph (8 nodes)

`LoadImage` → `VAEEncode` → `KSampler` ← `CLIPTextEncode` (positive/negative) ← `CheckpointLoaderSimple` → `VAEDecode` → `SaveImage`

## Defaults

| Parameter | Value |
|-----------|-------|
| Checkpoint | `sd15.safetensors` |
| Denoise | ~0.55 (range 0.45–0.65) |
| Steps | 24 |
| CFG | 7.0 |
| Sampler | euler (matches base txt2img) |
| Output prefix | `ai_studio_base_img2img` |

## Inputs

- Source image (Drive: `AI_Studio/inputs/images/` or any eligible path)
- Positive / negative prompts (editable in ComfyUI)

## Preparation

```bash
python core/scripts/prepare_workflow.py --workflow img2img --input /path/to/source.png
```

## Outputs

- PNG image → ComfyUI `output/` with prefix `ai_studio_base_img2img`

## Known Limitations

- High denoise (>0.7) effectively becomes txt2img with the image as initial noise.
- SD1.5 img2img does not preserve fine identity details for downstream identity-lock workflows.
