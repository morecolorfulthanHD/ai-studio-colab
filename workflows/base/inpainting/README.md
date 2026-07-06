# inpainting

**Status:** Not yet implemented (Phase 3)

## Purpose

Regenerate a masked region of an image while preserving the unmasked areas.

## Required Models

| Model | Location |
|-------|----------|
| SD 1.5 inpainting checkpoint | `assets/checkpoints/` |

## Required Nodes

None beyond stock ComfyUI (inpaint-specific checkpoint required).

## Inputs

- Source image
- Mask image (white = inpaint region)
- Prompts
- Preset key

## Outputs

- Inpainted PNG → `output/`

## Dependencies

- Source image and mask

## Known Limitations

- Requires inpainting-specific checkpoint for best seam blending.
