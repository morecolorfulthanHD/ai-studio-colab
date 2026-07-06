# ControlNet — Segmentation

**Status:** Not yet implemented (Phase 2)

## Purpose

Generate images guided by semantic segmentation maps for region-level control.

## Inputs

- Segmentation map (from `extraction/segmentation_map/` or manual)
- Prompts, preset key

## Outputs

- PNG with segmentation-guided layout → `output/`

## Dependencies

- `workflows/extraction/segmentation_map/` (recommended)
- ComfyUI Impact Pack (segmentation preprocessor)
