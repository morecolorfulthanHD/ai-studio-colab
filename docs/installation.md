# Installation

Setup and launch procedures for AI Studio Colab.

**Current phase:** Epic 2 Package 1 — runtime platform with structured health reporting and install planners.

## Prerequisites

- Google Colab with GPU runtime (T4 minimum; A100 recommended for video workflows)
- Google Drive for persistent model and output storage
- A clone of this repository (GitHub, private mirror, or manual copy)
- Sufficient Drive/disk space for model weights (see `configs/models/model_registry.json`)

## Canonical Entry Point

Open the control panel notebook in Google Colab:

**[`colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb`](../colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb)**

This is the only launcher. Do not create duplicate notebooks. See [colab-control-panel.md](colab-control-panel.md).

## Installation Flow

### 1. Clone the Repository

In Colab or locally:

```bash
# Example — adjust URL for your remote
git clone <your-repo-url> /content/ai-studio-colab
cd /content/ai-studio-colab
```

The repository is the **source of truth** for workflows, configs, scripts, and documentation.

### 2. Run Bootstrap Validation

From the control panel notebook (**Cell 3b — Repository Bootstrap & Validation**) or manually:

```bash
python core/scripts/bootstrap_repo.py
python core/scripts/validate_environment.py
python core/scripts/validate_paths.py
python core/scripts/validate_manifests.py
python core/scripts/list_workflows.py
```

After ComfyUI is installed, also run:

```bash
python core/scripts/check_nodes.py
python core/scripts/verify_models.py
```

These scripts validate structure and manifests. They do not install software or download models.

### 2b. Runtime Platform Health

From **Cell 3c — Runtime Platform Health** or manually:

```bash
python core/scripts/runtime_report.py
python core/scripts/runtime_report.py --summary
python core/scripts/runtime_report.py --json
```

Install planners (dry-run only — no downloads):

```bash
python core/comfyui/install_nodes.py --dry-run
python core/comfyui/install_models.py --dry-run
python core/a1111/install.py --dry-run
```

See [runtime-platform.md](runtime-platform.md).

### 3. Mount Google Drive

Use the control panel notebook to mount Drive. Persistent storage root:

```
/content/drive/MyDrive/AI_Studio
```

Path mappings are defined in `configs/paths/colab_paths.json`.

### 4. Install ComfyUI Runtime

**Option A — repo install script (recommended for bootstrap):**

```bash
bash core/comfyui/install.sh
```

**Option B — control panel notebook (Cell 9):** `install_comfyui()` with safe/minimal/full modes.

Both install to `/content/ComfyUI` and symlink models to Drive at `drive_models`.

| Engine | Runtime Path | Install |
|--------|-------------|---------|
| ComfyUI | `/content/ComfyUI` | `core/comfyui/install.sh` or notebook Cell 9 |
| A1111 | `/content/A1111` | notebook Cell 9 (`install_a1111`) |

Install scripts in `core/automatic1111/` are planned for a future phase.

### 5. Install Models

Models are stored on Drive at `drive_models` (`/content/drive/MyDrive/AI_Studio/models/shared`) or in repo `assets/` for local dev. Binary weights are not committed to Git.

Model requirements are catalogued in `configs/models/model_registry.json`. Download logic will be added in a future phase.

### 6. Install Custom Nodes

Custom nodes are defined in `configs/nodes/node_registry.json`:

- ComfyUI-Manager
- ComfyUI-Impact-Pack
- ComfyUI-AnimateDiff-Evolved
- ComfyUI-ReActor
- comfyui_controlnet_aux
- was-node-suite-comfyui

Install automation is planned; the notebook currently handles runtime installs.

### 7. Verify with Bootstrap Scripts

```bash
python core/scripts/list_workflows.py
python core/scripts/sync_outputs.py --dry-run
```

## Launching

| Environment | Method |
|-------------|--------|
| Google Colab | `colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb` |
| Local (future) | `core/comfyui/launch.sh` |

## Updating

1. Pull latest repository changes (`git pull` — explicit, not automatic)
2. Re-run `validate_manifests.py` to confirm config compatibility
3. Re-run notebook install cells when `configs/nodes/` changes
4. Add new models when `configs/models/model_registry.json` changes

`bootstrap_repo.py` documents a future git sync hook but does not auto-pull.

## Path Configuration

All Colab and Drive paths are in `configs/paths/colab_paths.json`:

| Key | Path |
|-----|------|
| `drive_root` | `/content/drive/MyDrive/AI_Studio` |
| `comfyui_runtime` | `/content/ComfyUI` |
| `a1111_runtime` | `/content/A1111` |
| `comfyui_output` | `/content/ComfyUI/output` |
| `drive_outputs` | `/content/drive/MyDrive/AI_Studio/outputs` |
| `drive_models` | `/content/drive/MyDrive/AI_Studio/models/shared` |
| `drive_workflows` | `/content/drive/MyDrive/AI_Studio/workflows` |

## Troubleshooting

See [troubleshooting.md](troubleshooting.md).
