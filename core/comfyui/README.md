# ComfyUI

Primary workflow engine for AI Studio Colab.

## Install Script

**`install.sh`** — ComfyUI install + validation script (safe by default).

```bash
# Default: dry-run only
bash core/comfyui/install.sh

# Execute install/update
bash core/comfyui/install.sh --execute

# Archive existing runtime and clone fresh
bash core/comfyui/install.sh --execute --force-reinstall
```

### What it does

| Step | Action |
|------|--------|
| 1 | Classify `/content/ComfyUI` runtime state |
| 2 | Recover safely from empty or partial installs when evidence is strong |
| 3 | Clone or update ComfyUI from the official repository |
| 4 | Validate or install Python requirements via `pip` |
| 5 | Configure persistent Drive models via `extra_model_paths.yaml` |

### Runtime directory classifications

| Classification | Meaning | Automatic recovery |
|----------------|---------|--------------------|
| `missing` | Runtime path does not exist | Clone fresh |
| `valid_git_repo` | Valid ComfyUI git checkout with recognized origin and core structure | Pull latest changes |
| `empty_directory` | Directory exists but has no meaningful entries | Remove empty dir, clone fresh |
| `partial_comfyui_install` | Strong ComfyUI-like evidence without `.git` | Archive to timestamped backup, clone fresh |
| `unknown_non_git_directory` | Unrelated or ambiguous contents | Stop safely; manual action required |

Partial-install detection requires strong evidence such as combinations of `main.py`, `requirements.txt`, `comfy/`, `web/`, `nodes.py`, `folder_paths.py`, `models/`, and related runtime folders. A directory is **not** classified as partial merely because its name is `ComfyUI`.

An **orphan `custom_nodes` runtime** — a non-git directory containing only `custom_nodes/` with no `main.py`, `requirements.txt`, or other significant top-level entries — is also classified as `partial_comfyui_install`. Recovery archives it to `ComfyUI.broken.<UTC timestamp>` and clones fresh. Any `custom_nodes` content is preserved in the archive but is **not** restored automatically.

Git repositories are classified as `valid_git_repo` only when the `origin` remote matches `COMFYUI_REPO` or `Comfy-Org/ComfyUI` and distinctive ComfyUI paths such as `comfy/`, `nodes.py`, or `folder_paths.py` are present. Unrecognized git repositories are never pulled automatically.

### Archive locations

When recovery archives an existing runtime, it is renamed — never permanently deleted:

```text
/content/ComfyUI.broken.<UTC timestamp>
/content/ComfyUI.archived.<UTC timestamp>
```

If a timestamped archive path already exists, the installer adds a numeric suffix (`.1`, `.2`, …) and never overwrites an existing archive.

Inspect or remove old archives manually:

```bash
ls -ld /content/ComfyUI.broken.* /content/ComfyUI.archived.*
```

### What it does not do

- Download model weights
- Delete Drive models
- Permanently delete unknown runtime directories
- Remove unrelated user-managed directories without `--force-reinstall --execute`

### Environment overrides

| Variable | Default |
|----------|---------|
| `COMFYUI_DIR` | `/content/ComfyUI` |
| `SHARED_MODELS` | `/content/drive/MyDrive/AI_Studio/models/shared` |
| `COMFYUI_REPO` | `https://github.com/Comfy-Org/ComfyUI.git` |
| `PYTHON` | `python3` |
| `EXTRA_MODEL_PATHS_FILE` | `/content/ComfyUI/extra_model_paths.yaml` |

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
| `install.sh` | Clone ComfyUI, deps, extra model paths | Done |
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

ComfyUI reads checkpoints, LoRAs, VAEs, and ControlNets from the Drive-backed shared models folder via `extra_model_paths.yaml`. The native `/content/ComfyUI/models` directory remains local to the runtime. Repo `assets/` paths are used for local development; Colab runtime uses `configs/paths/colab_paths.json` → `drive_models`.
