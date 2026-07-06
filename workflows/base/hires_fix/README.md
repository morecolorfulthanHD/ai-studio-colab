# hires_fix

**Status:** Not yet implemented (Phase 2)

## Purpose

Two-pass generation: initial render at lower resolution, then upscale and refine for higher detail.

## Required Models

| Model | Location |
|-------|----------|
| SD 1.5 checkpoint | `assets/checkpoints/` |
| Upscaler | `assets/upscalers/` |

## Required Nodes

None beyond stock ComfyUI.

## Inputs

- Prompts and preset from `txt2img/` pass
- Upscale factor (1.5x, 2x)
- Hires denoise strength

## Outputs

- High-resolution PNG → `output/`

## Dependencies

- Typically chained after `txt2img/` or used as a sub-graph within pipelines

## Known Limitations

- Increases VRAM usage and generation time proportionally to upscale factor.
