# ComfyUI

Primary workflow engine for AI Studio Colab.

## Contents (Phase 1+)

| Item | Purpose |
|------|---------|
| `install.sh` | Clone ComfyUI, install dependencies, wire model paths |
| `install_nodes.sh` | Install custom nodes from `configs/nodes/` manifest |
| `launch.sh` | Start ComfyUI server with correct paths |
| `custom_nodes/` | Symlinks or clones managed by install script |

The `ComfyUI/` directory itself is gitignored and created at install time.

## Model Path Wiring

ComfyUI reads checkpoints, LoRAs, VAEs, and ControlNets from `assets/` via symlinks in `core/shared_models/` and extra path config in `configs/paths/`.
