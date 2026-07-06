# Shared Nodes

Custom node repositories used across ComfyUI (and where applicable, A1111 extensions).

## Purpose

Centralize custom node clones so install scripts in `core/comfyui/` and `core/automatic1111/` reference a single source. Versions are pinned in `configs/nodes/`.

## Planned Node Packs

| Pack | Phase | Used By |
|------|-------|---------|
| ControlNet Aux | 2 | Preprocessor extraction workflows |
| ComfyUI Impact Pack | 2 | Segmentation, detailer nodes |
| WAS Node Suite | 2 | Image utilities |
| IPAdapter nodes | 3 | Reference locking workflows |
| AnimateDiff nodes | 6 | Animation workflows |
| ReActor nodes | 5 | Face swap and identity |

Node repos are gitignored here and cloned at install time per `configs/nodes/` manifest.
