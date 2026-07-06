# Multi-Reference

**Status:** Not yet implemented (Phase 3)

## Purpose

Combine multiple reference images (face, clothing, environment, pose) into a single generation with weighted influence per reference.

## Inputs

- Multiple reference images with role tags (face, style, environment, etc.)
- Per-reference weight values
- Prompts, preset key

## Outputs

- Multi-reference-conditioned PNG → `output/`

## Dependencies

- `reference/ipadapter/`
- Optionally `controlnet/` for structural maps from one of the references
