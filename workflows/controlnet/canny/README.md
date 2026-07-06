# ControlNet — Canny

**Status:** Not yet implemented (Phase 2)

## Purpose

Generate images guided by Canny edge detection maps for precise structural control.

## Inputs

- Canny edge map (from `extraction/` or manual)
- Prompts, preset key

## Outputs

- PNG guided by edge structure → `output/`

## Dependencies

- `workflows/extraction/` (if extracting from source image)
