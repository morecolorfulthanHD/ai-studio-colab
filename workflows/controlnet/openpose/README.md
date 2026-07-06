# ControlNet — OpenPose

**Status:** Not yet implemented (Phase 2)

## Purpose

Generate images guided by human pose skeletons for body position and gesture control.

## Inputs

- OpenPose map (from `extraction/pose_map/` or manual)
- Prompts, preset key

## Outputs

- PNG with pose-guided figure → `output/`

## Dependencies

- `workflows/extraction/pose_map/` (recommended)
