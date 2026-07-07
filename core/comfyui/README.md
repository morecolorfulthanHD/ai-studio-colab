# ComfyUI

Primary workflow engine for AI Studio Colab.

## Install Script

**`install.sh`** — Colab-safe, idempotent ComfyUI installer.

```bash
# From repository root (Colab)
bash core/comfyui/install.sh

# Force fresh clone
FORCE_REINSTALL=1 bash core/comfyui/install.sh
```

### What it does

| Step | Action |
|------|--------|
| 1 | Clone ComfyUI to `/content/ComfyUI` (or `git pull` if already present) |
| 2 | Install Python requirements via `pip` |
| 3 | Symlink `/content/ComfyUI/models` → `/content/drive/MyDrive/AI_Studio/models/shared` |

### What it does not do

- Install custom nodes (use `install_nodes.py` planner or notebook Node Manager)
- Download model weights
- Remove existing installs unless `FORCE_REINSTALL=1`

### Environment overrides

| Variable | Default |
|----------|---------|
| `COMFYUI_DIR` | `/content/ComfyUI` |
| `SHARED_MODELS` | `/content/drive/MyDrive/AI_Studio/models/shared` |
| `COMFYUI_REPO` | `https://github.com/Comfy-Org/ComfyUI.git` |
| `PYTHON` | `python3` |
| `FORCE_REINSTALL` | `0` |

## Control Panel Integration

The notebook's Cell 9 (`install_comfyui`) provides an in-notebook installer with additional node support. `install.sh` is the repo-managed, scriptable equivalent for:

- Notebook cells that shell out to the repo install layer
- Future `colab/launch/` bootstrap scripts
- CI or documentation-driven installs

Both approaches target the same runtime path (`/content/ComfyUI`) and shared models directory.

## Install Planners (dry-run)

| Script | Purpose |
|--------|---------|
| `install_nodes.py` | Plan custom node clones from `node_registry.json` |
| `install_models.py` | Plan model placement from `model_registry.json` |

```bash
python core/comfyui/install_nodes.py --dry-run
python core/comfyui/install_models.py --dry-run
```

Execution deferred to Epic 2 Package 2. Plans are consumed by `RuntimeManager.plan_comfyui_install()`.

## Planned Files

| Item | Purpose | Status |
|------|---------|--------|
| `install.sh` | Clone ComfyUI, deps, model symlink | Done |
| `install_nodes.py` | Node install plan (dry-run) | Done |
| `install_models.py` | Model install plan (dry-run) | Done |
| `install_nodes.sh` | Execute node install plan | Planned |
| `launch.sh` | Start ComfyUI server | Planned |

The `ComfyUI/` runtime directory is gitignored and created at install time.

## Validation

After install, verify nodes and models:

```bash
python core/scripts/runtime_report.py
python core/scripts/check_nodes.py
python core/scripts/verify_models.py
```

## Model Path Wiring

ComfyUI reads checkpoints, LoRAs, VAEs, and ControlNets from the Drive-backed shared models folder via the `models` symlink. Repo `assets/` paths are used for local development; Colab runtime uses `configs/paths/colab_paths.json` → `drive_models`.
