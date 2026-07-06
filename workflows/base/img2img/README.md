# img2img

**Status:** Not yet implemented (Phase 2)

## Purpose

Refine or restyle an existing image using denoise strength to control how much of the original is preserved.

## Required Models

| Model | Location |
|-------|----------|
| SD 1.5 checkpoint | `assets/checkpoints/` |
| SD 1.5 VAE | `assets/vaes/` |

## Required Nodes

None beyond stock ComfyUI.

## Inputs

- Source image
- Positive / negative prompts
- Denoise strength (0.0–1.0)
- Preset key from `configs/presets/`

## Outputs

- Refined PNG image → `output/`

## Dependencies

- Source image (user-provided or output from `txt2img/`)

## Known Limitations

- High denoise (>0.7) effectively becomes txt2img with image as initial noise.
