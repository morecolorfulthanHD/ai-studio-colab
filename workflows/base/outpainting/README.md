# outpainting

**Status:** Not yet implemented (Phase 3)

## Purpose

Extend the canvas beyond the original image boundaries, generating new content in the expanded area.

## Required Models

| Model | Location |
|-------|----------|
| SD 1.5 checkpoint | `assets/checkpoints/` |

## Required Nodes

None beyond stock ComfyUI.

## Inputs

- Source image
- Expansion direction and pixel amount (or target aspect ratio)
- Prompts describing the extended scene
- Preset key

## Outputs

- Expanded PNG → `output/`

## Dependencies

- Source image

## Known Limitations

- Large expansions may produce seams; iterative small expansions often work better.
