# Stable Video Diffusion (SVD)

**Status:** Not yet implemented (Phase 6)

## Purpose

Generate a video clip from a single still image using Stable Video Diffusion.

## Inputs

- Source still image
- Motion bucket, FPS, frame count
- Preset key

## Outputs

- MP4 video clip → `output/`

## Dependencies

- SVD checkpoint in `assets/checkpoints/`
- SVD ComfyUI nodes

## Known Limitations

- High VRAM requirement; A100 recommended for stable results.
