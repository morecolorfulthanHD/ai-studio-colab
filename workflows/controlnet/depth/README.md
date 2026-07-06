# ControlNet — Depth

**Status:** Not yet implemented (Phase 2)

## Purpose

Generate images guided by depth maps for spatial and compositional control.

## Inputs

- Depth map (from `extraction/depth_map/` or manual)
- Prompts, preset key

## Outputs

- PNG with depth-guided composition → `output/`

## Dependencies

- `workflows/extraction/depth_map/` (recommended)
