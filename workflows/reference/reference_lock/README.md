# Reference Lock

**Status:** Not yet implemented (Phase 3)

## Purpose

Lock specific visual attributes (color palette, composition, style) from a reference image across generations.

## Inputs

- Reference image
- Prompts
- Lock strength parameter
- Base or ControlNet workflow preset

## Outputs

- Generated image with locked reference attributes → `output/`

## Dependencies

- `base/txt2img/` or `controlnet/` workflow as generation backbone
