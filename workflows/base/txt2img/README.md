# txt2img

**Status:** Not yet implemented (Phase 1)

## Purpose

Generate an image from a text prompt using an SD 1.5 checkpoint.

## Required Models

| Model | Location |
|-------|----------|
| SD 1.5 checkpoint | `assets/checkpoints/` |
| SD 1.5 VAE | `assets/vaes/` |

## Required Nodes

None beyond stock ComfyUI.

## Inputs

- Positive prompt (string)
- Negative prompt (string)
- Preset key from `configs/presets/` (sampler, steps, CFG, resolution, seed)

## Outputs

- Single PNG image → `output/`

## Dependencies

None. This is the entry-point workflow.

## Recommended Settings

Defined in `configs/presets/sd15_standard.yaml` (to be created in Phase 1).

## Known Limitations

- SD 1.5 only in Phase 1; SDXL and Flux support planned for future phases.
