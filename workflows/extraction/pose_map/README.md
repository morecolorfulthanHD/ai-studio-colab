# Extraction — Pose Map

**Status:** Not yet implemented (Phase 2)

## Purpose

Extract an OpenPose skeleton map from a source image for use with `controlnet/openpose/`.

## Inputs

- Source image (must contain detectable human figure)

## Outputs

- OpenPose skeleton PNG → `output/`

## Dependencies

- ControlNet Aux OpenPose preprocessor

## Known Limitations

- Requires visible human body; fails silently or produces empty map for non-human subjects.
