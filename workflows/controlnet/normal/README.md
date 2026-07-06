# ControlNet — Normal

**Status:** Not yet implemented (Phase 2)

## Purpose

Generate images guided by surface normal maps for lighting and 3D surface consistency.

## Inputs

- Normal map (from `extraction/normal_map/` or manual)
- Prompts, preset key

## Outputs

- PNG with normal-guided surfaces → `output/`

## Dependencies

- `workflows/extraction/normal_map/` (recommended)
