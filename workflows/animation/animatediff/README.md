# AnimateDiff

**Status:** Not yet implemented (Phase 6)

## Purpose

Generate short animated clips from a text prompt or a single reference image.

## Inputs

- Prompt and/or seed image
- Frame count, FPS
- Motion module selection
- Preset key

## Outputs

- Animated GIF or MP4 → `output/`

## Dependencies

- AnimateDiff custom nodes
- AnimateDiff motion module weights

## Known Limitations

- Short clips only (16–32 frames typical); temporal consistency degrades on longer sequences.
