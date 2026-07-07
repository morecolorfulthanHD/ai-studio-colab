# ComfyUI

Primary workflow engine for AI Studio Colab.

## Install Script

**`install.sh`** — ComfyUI install + validation script (safe by default).

```bash
# Default: dry-run only
bash core/comfyui/install.sh

# Execute install/update
bash core/comfyui/install.sh --execute

# Execute with destructive reinstall
bash core/comfyui/install.sh --execute --force-reinstall
```

### What it does

| Step | Action |
|------|--------|
| 1 | Validate or clone ComfyUI to `/content/ComfyUI` |
| 2 | Validate or install Python requirements via `pip` |
| 3 | Validate or create `/content/ComfyUI/models` symlink to Drive shared models |

### What it does not do

- Download model weights
- Delete Drive models
- Remove existing installs unless `--force-reinstall` is explicitly provided

### Environment overrides

| Variable | Default |
|----------|---------|
| `COMFYUI_DIR` | `/content/ComfyUI` |
| `SHARED_MODELS` | `/content/drive/MyDrive/AI_Studio/models/shared` |
| `COMFYUI_REPO` | `https://github.com/Comfy-Org/ComfyUI.git` |
| `PYTHON` | `python3` |
## Node + Model scripts

| Script | Default behavior | Execute mode |
|--------|-------------------|--------------|
| `install_nodes.py` | Dry-run plan and status output | `--execute` clones missing nodes and installs per-node requirements when present |
| `install_models.py` | Dry-run model validation summary | `--execute` validates model readiness only (no downloads) |

```bash
python core/comfyui/install_nodes.py --dry-run
python core/comfyui/install_nodes.py --execute
python core/comfyui/install_models.py --dry-run
python core/comfyui/install_models.py --execute
```

## Control Panel Integration

The notebook's Cell 9 (`install_comfyui`) provides an in-notebook installer with additional node support. `install.sh` is the repo-managed, scriptable equivalent for:

- Notebook cells that shell out to the repo install layer
- Future `colab/launch/` bootstrap scripts
- CI or documentation-driven installs

Both approaches target the same runtime path (`/content/ComfyUI`) and shared models directory.

## Install Planning and Execution

Both scripts consume:

- `configs/nodes/node_registry.json`
- `configs/models/model_registry.json`
- `configs/assets/asset_registry.json`

Model downloads are intentionally deferred to a later package.

## Planned Files

| Item | Purpose | Status |
|------|---------|--------|
| `install.sh` | Clone ComfyUI, deps, model symlink | Done |
| `install_nodes.py` | Node install plan + execute mode | Done |
| `install_models.py` | Model validation plan + execute mode | Done |
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
