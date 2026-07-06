# ControlNet Workflows

ControlNet-guided generation using structural maps (pose, depth, edges, etc.).

**Status:** Not yet implemented (Phase 2)

| Workflow | Control Type |
|----------|-------------|
| [canny/](canny/) | Edge detection map |
| [depth/](depth/) | Depth map |
| [openpose/](openpose/) | Human pose skeleton |
| [normal/](normal/) | Surface normal map |
| [segmentation/](segmentation/) | Semantic segmentation map |
| [lineart/](lineart/) | Line art extraction map |

## Pattern

1. Run matching `workflows/extraction/` workflow on source image
2. Feed extracted map into corresponding ControlNet workflow here
3. Combine with `reference/` workflows for identity locking when needed

## Required Nodes

- ControlNet Aux (preprocessors — used in extraction)
- Stock ComfyUI ControlNet nodes

## Required Models

ControlNet weights in `assets/controlnets/` — one per type. See `configs/models/`.
