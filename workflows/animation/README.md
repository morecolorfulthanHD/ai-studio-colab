# Animation Workflows

Motion and video generation pipelines.

**Status:** Not yet implemented (Phase 6)

| Workflow | Output |
|----------|--------|
| [animatediff/](animatediff/) | Short animated clip (GIF/MP4) |
| [svd/](svd/) | Video from still image (Stable Video Diffusion) |
| [image_sequence/](image_sequence/) | Numbered frame sequence |

## Dependencies

Built on top of `pipelines/` and `reference/` workflows — still images are generated first, then animated.

## Required Nodes

- AnimateDiff nodes
- SVD nodes (ComfyUI video nodes)

## Required Models

- AnimateDiff motion modules
- SVD checkpoint → `assets/checkpoints/`
