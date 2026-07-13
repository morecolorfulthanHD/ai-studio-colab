# Installation

Setup and launch procedures for AI Studio Colab.

**Current phase:** Production Package 4 — image editing foundation (img2img, inpainting, outpainting).

## Prerequisites

- Google Colab with GPU runtime (T4 minimum; A100 recommended for video workflows)
- Google Drive for persistent model and output storage
- Sufficient Drive/disk space for model weights (see `configs/models/model_registry.json`)

No manual repository clone is required — the notebook **Repository Sync** cell handles clone/pull from GitHub.

## Source of Truth

| Location | Role |
|----------|------|
| **GitHub** | Canonical source for notebook, scripts, configs, workflows, and docs |
| **Google Drive** | Persistent storage for models, outputs, datasets, references, checkpoints |
| **Colab runtime** | Disposable workspace — repo cloned to `/content/ai-studio-colab` each session |

Google Drive is **not** the canonical notebook source. Do not treat a Drive-saved `.ipynb` as the authoritative copy.

## Canonical Entry Point

Open the control panel notebook **from GitHub** in Google Colab:

**[`colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb`](../colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb)**

Direct Colab link:

**https://colab.research.google.com/github/morecolorfulthanHD/ai-studio-colab/blob/main/colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb**

This is the only launcher. Do not create duplicate notebooks. See [colab-control-panel.md](colab-control-panel.md).

### Optional: Old Drive Copy Fallback

If you previously saved the notebook on Drive, it may still open as a convenience launcher. **Repository Sync** will pull the latest repo code from GitHub, but the notebook cells themselves come from whichever file you opened. Periodically switch to the GitHub Colab link above so you run the current canonical notebook.

## Installation Flow

### 1. Sync the Repository (Colab)

Run the notebook **Repository Sync** cell (after Cells 1–3). It automatically:

- **Clones** `https://github.com/morecolorfulthanHD/ai-studio-colab.git` into `/content/ai-studio-colab` if missing
- **Pulls** the latest changes if the repo already exists

For local development:

```bash
git clone https://github.com/morecolorfulthanHD/ai-studio-colab.git
cd ai-studio-colab
```

GitHub is the **source of truth** for the notebook, workflows, configs, scripts, and documentation.

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

### 2b. Runtime Platform Health and Install Dry-Runs

From **Cell 3c** or manually:

```bash
python core/scripts/runtime_report.py --summary
python core/scripts/validate_assets.py --summary
python core/scripts/validate_capabilities.py --summary
python core/scripts/runtime_report.py --json
```

Install/validation scripts (safe by default):

```bash
python core/comfyui/install_nodes.py --dry-run
python core/comfyui/install_models.py --dry-run
bash core/comfyui/install.sh
```

See [runtime-platform.md](runtime-platform.md).

### 3. Mount Google Drive

Use the control panel notebook to mount Drive. Persistent storage root:

```
/content/drive/MyDrive/AI_Studio
```

Path mappings are defined in `configs/paths/colab_paths.json`.

### 4. Install or Validate ComfyUI Runtime

**Option A — repo install script (recommended for bootstrap + reproducibility):**

```bash
bash core/comfyui/install.sh                # dry-run
bash core/comfyui/install.sh --execute      # apply
```

**Option B — control panel notebook (Cell 9):** `install_comfyui()` with safe/minimal/full modes.

Both paths target `/content/ComfyUI` and symlink models to Drive at `drive_models`.

| Engine | Runtime Path | Install |
|--------|-------------|---------|
| ComfyUI | `/content/ComfyUI` | `core/comfyui/install.sh` or notebook Cell 9 |
| A1111 | `/content/A1111` | notebook Cell 9 (`install_a1111`) |

Install scripts in `core/automatic1111/` are planned for a future phase.

### 5. Validate Models (No Downloads in This Package)

Models are stored on Drive at `drive_models` (`/content/drive/MyDrive/AI_Studio/models/shared`) or in repo `assets/` for local dev. Binary weights are not committed to Git.

Model requirements are catalogued in `configs/models/model_registry.json`.

```bash
python core/scripts/verify_models.py
python core/comfyui/install_models.py --dry-run
python core/comfyui/install_models.py --execute
```

`install_models.py --execute` performs validation only and fails when required base model readiness is missing. It does not download models.

### 6. Install or Validate Default Custom Nodes

Custom nodes are defined in `configs/nodes/node_registry.json`:

- ComfyUI-Manager
- ComfyUI-Impact-Pack
- ComfyUI-AnimateDiff-Evolved
- ComfyUI-ReActor
- comfyui_controlnet_aux
- was-node-suite-comfyui

Install execution is available:

```bash
python core/comfyui/install_nodes.py --dry-run
python core/comfyui/install_nodes.py --execute
```

If a node folder exists, the script skips safely. Missing optional nodes are reported without aborting required paths.

### 7. Load Base txt2img Workflow

Workflow path:

```text
workflows/base/txt2img/workflow.json
```

In ComfyUI:

1. Open ComfyUI UI.
2. Load workflow JSON from the repository path above.
3. Ensure checkpoint `sd15.safetensors` is available in ComfyUI models.
4. Queue prompt to generate baseline output.

### 8. Verify with Runtime Scripts

```bash
python core/scripts/list_workflows.py
python core/scripts/dogfood_core_runtime.py
python core/scripts/sync_outputs.py --dry-run
```

## Single-Button Launch (Control Panel)

After Repository Sync and bootstrap cells, run `control_panel()` and choose **1. Launch**.

| Mode | What it does |
|------|----------------|
| **safe** | `install.sh --execute`, SD1.5 check, launch ComfyUI |
| **minimal** | safe + base txt2img workflow path and import instructions |
| **full** | minimal + `install_nodes.py --execute` for registered stable nodes |

Launch uses repo scripts (not duplicated notebook logic):

```bash
bash core/comfyui/install.sh --execute
python core/comfyui/install_nodes.py --execute   # full mode only
python core/scripts/verify_models.py
python core/scripts/runtime_report.py --summary
python core/scripts/dogfood_core_runtime.py
```

### SD1.5 Checkpoint (Required for txt2img)

Expected path (manual placement — no auto-download):

```text
/content/drive/MyDrive/AI_Studio/models/shared/checkpoints/sd15.safetensors

### SD1.5 Inpainting Checkpoint (Required for inpainting)

```text
/content/drive/MyDrive/AI_Studio/models/shared/checkpoints/512-inpainting-ema.safetensors
```

No automatic download occurs. You must place this checkpoint manually and review model licensing/source before use.
```

Verify:

```bash
python core/scripts/verify_models.py --require-sd15
```

### Base txt2img Workflow

```text
/content/ai-studio-colab/workflows/base/txt2img/workflow.json
```

After ComfyUI launches: open the URL → import workflow → confirm `sd15.safetensors` → queue prompt → check `/content/ComfyUI/output`.

### Output Sync

```bash
python core/scripts/sync_outputs.py --dry-run
python core/scripts/sync_outputs.py
```

For end-to-end Colab validation (bootstrap → install → txt2img → output copy), follow
[dogfooding/core-runtime-txt2img-checklist.md](dogfooding/core-runtime-txt2img-checklist.md).

### Image editing inputs (Drive)

Create persistent input folders (placeholders only in Git; add your own images on Drive):

```text
/content/drive/MyDrive/AI_Studio/inputs/images/
/content/drive/MyDrive/AI_Studio/inputs/masks/
```

List eligible files:

```bash
python core/scripts/list_inputs.py
```

Prepare and stage into ComfyUI `input/`:

```bash
python core/scripts/prepare_workflow.py --workflow img2img --input /content/drive/MyDrive/AI_Studio/inputs/images/your_image.png
python core/scripts/prepare_workflow.py --workflow inpainting --input /path/to/source.png --mask /path/to/mask.png
python core/scripts/prepare_workflow.py --workflow outpainting --input /path/to/source.png --left 256 --right 256
python core/scripts/prepare_workflow.py --workflow img2img --input /path/to/image.png --dry-run
```

**Dogfooding sequence:** Drive inputs → list → prepare (stages to ComfyUI/input) → import prepared workflow → generate → sync → verify evidence.

| Capability | Canonical workflow | Preparation |
|------------|-------------------|-------------|
| img2img | `workflows/base/img2img/workflow.json` | `prepare_workflow.py --workflow img2img --input <path>` |
| inpainting | `workflows/base/inpainting/workflow.json` | `--workflow inpainting --input <path> --mask <path>` (checkpoint `512-inpainting-ema.safetensors`, denoise 1.0) |
| outpainting | `workflows/base/outpainting/workflow.json` | `--workflow outpainting --input <path> --left N` (denoise 1.0) |

Preparation stages selected files into ComfyUI `input/` with content-based reuse (SHA-256) and collision-safe naming when needed. Load the prepared JSON in ComfyUI.

Base inpainting and outpainting both use `VAEEncodeForInpaint` with KSampler denoise **1.0**. Inpainting additionally requires the dedicated inpainting checkpoint (`512-inpainting-ema.safetensors`). Prefer iterative 128–256 px canvas extensions for outpainting.

Control panel shortcut: `control_panel()` → **7. Image Editing**.

SD1.5 base outpainting has quality limitations — prefer iterative small expansions. See [workflows/base/outpainting/README.md](../workflows/base/outpainting/README.md).

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
| `drive_inputs` | `/content/drive/MyDrive/AI_Studio/inputs` |
| `runtime_workflows` | `/content/ai-studio-runtime/workflows` |
| `drive_models` | `/content/drive/MyDrive/AI_Studio/models/shared` |
| `drive_workflows` | `/content/drive/MyDrive/AI_Studio/workflows` |

## Troubleshooting

See [troubleshooting.md](troubleshooting.md).
