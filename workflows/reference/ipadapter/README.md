# IPAdapter

**Status:** Not yet implemented (Phase 3)

## Purpose

Condition generation on a reference image using IPAdapter for style, composition, and partial identity transfer.

## Required Models

| Model | Location |
|-------|----------|
| IPAdapter SD 1.5 | `assets/ipadapter/` |
| CLIP vision | `assets/clip/` |

## Inputs

- Reference image
- IPAdapter weight/strength
- Prompts, preset key

## Outputs

- Reference-conditioned PNG → `output/`

## Dependencies

- IPAdapter custom nodes (see `configs/nodes/`)
