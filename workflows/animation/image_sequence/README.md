# Image Sequence

**Status:** Not yet implemented (Phase 6)

## Purpose

Generate a numbered sequence of related frames for manual animation assembly or downstream video tools.

## Inputs

- Keyframe prompts (list) or interpolation between two seed images
- Per-frame ControlNet maps (optional)
- Camera movement parameters (optional)

## Outputs

- Numbered PNG sequence → `output/<sequence_name>/`

## Dependencies

- `base/` or `pipelines/` workflows for per-frame generation
- `controlnet/` for consistent structural guidance across frames

## Use Cases

- Camera pan/zoom sequences
- Character pose sequences
- Environment walkthrough frames
