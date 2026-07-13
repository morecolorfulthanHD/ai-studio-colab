# Colab Control Panel

The canonical launcher for AI Studio Colab is a single notebook **in this GitHub repository**:

**`colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb`**

Open it in Colab from GitHub (not from a Drive copy):

**https://colab.research.google.com/github/morecolorfulthanHD/ai-studio-colab/blob/main/colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb**

This notebook is the official control panel. Do not duplicate it. Future improvements should enhance this notebook rather than replace it.

## GitHub vs. Google Drive

| Location | Canonical? | Purpose |
|----------|------------|---------|
| **GitHub** (`morecolorfulthanHD/ai-studio-colab`) | **Yes** | Notebook, scripts, configs, workflows, docs |
| **Google Drive** (`/content/drive/MyDrive/AI_Studio`) | No | Models, outputs, datasets, references, checkpoints |
| **Colab runtime** (`/content/ai-studio-colab`) | No | Disposable clone pulled from GitHub each session |

Google Drive is **not** the notebook source of truth. A `.ipynb` saved on Drive, if any, is only a convenience copy or launcher.

## Role in the Architecture

```
GitHub (canonical source of truth)     Google Drive (persistent storage)
        │                                    │
        │  clone / pull (Repository Sync)    │  models, outputs, datasets
        ▼                                    ▼
┌───────────────────────────────────────────────────────────────┐
│         AI_Studio_Control_Panel_Colab.ipynb  (from GitHub)    │
│  mount Drive · verify GPU · sync repo · validate · launch     │
└───────────────────────────┬───────────────────────────────────┘
                            │
            ┌───────────────┼───────────────┐
            ▼               ▼               ▼
  /content/ai-studio-colab  /content/ComfyUI  /content/A1111
  (cloned repo)             (runtime)         (runtime)
```

| Layer | Location | Persistence |
|-------|----------|-------------|
| **GitHub repository** | Canonical notebook, configs, workflows, scripts, docs | Permanent |
| **Colab runtime clone** | `/content/ai-studio-colab` (from Repository Sync) | Ephemeral per session |
| **Colab engines** | `/content/ComfyUI`, `/content/A1111` | Ephemeral — reinstalled each session |
| **Google Drive** | `/content/drive/MyDrive/AI_Studio` | Persistent models, outputs, datasets |
| **Bootstrap scripts** | `core/scripts/` (in cloned repo) | Called from notebook cells |

## What the Notebook Should Eventually Do

The control panel will become a self-updating AI Studio orchestrator:

| Capability | Status | Helper |
|------------|--------|--------|
| Mount Google Drive | In notebook (Cell 2) | — |
| Verify GPU | In notebook (Cell 1) | `validate_environment.py` |
| Sync / pull repo | **Repository Sync cell** | clones/pulls from GitHub |
| Repo bootstrap validation | Cell 3b | `bootstrap_repo.py`, `validate_manifests.py`, `list_workflows.py` |
| **Single-button Launch** | **control_panel() option 1** | `studio_launch()` → repo scripts |
| Launch ComfyUI | control_panel() Launch | `install.sh --execute`, `launch_comfyui()` |
| Install custom nodes | full Launch mode | `install_nodes.py --execute` |
| Validate models (SD1.5) | Launch flow | `verify_models.py` |
| Validate nodes | full Launch / Cell 3c | `check_nodes.py` |
| Sync outputs | Launch guidance + Cell 3c | `sync_outputs.py` |
| Runtime health | Cell 3c + post-launch | `runtime_report.py`, `dogfood_core_runtime.py` |
| Launch A1111 | Legacy Cell 9 installer | not part of Launch option 1 |
| Expose workflow menus | Planned | `list_workflows.py` + `workflow_registry.json` |
| Backup / restore workflows | Planned | Drive path `drive_workflows` |

## Single-Button Launch (Option 1)

Run `control_panel()` and choose **1. Launch**. Select a mode:

| Mode | ComfyUI | Nodes | SD1.5 | txt2img guidance |
|------|---------|-------|-------|------------------|
| **safe** | `install.sh --execute` + launch | skip | check (warn) | no |
| **minimal** | `install.sh --execute` + launch | skip | check (warn) | yes |
| **full** | `install.sh --execute` + launch | `install_nodes.py --execute` | check (warn) | yes |

The launch flow calls repo scripts rather than duplicating install logic:

```text
dogfood_core_runtime.py (pre)
install.sh --execute
install_nodes.py --execute        # full only
verify_models.py
launch_comfyui()
runtime_report.py --summary
dogfood_core_runtime.py (post)
```

After launch (minimal/full), the notebook prints:

- ComfyUI URL
- Base txt2img workflow path: `/content/ai-studio-colab/workflows/base/txt2img/workflow.json`
- Import/run instructions
- `sync_outputs.py` commands

SD1.5 expected path:

`/content/drive/MyDrive/AI_Studio/models/shared/checkpoints/sd15.safetensors`

No automatic model download is performed.

## Image Editing (Option 7)

Run `control_panel()` and choose **7. Image Editing** for img2img, inpainting, or outpainting:

| Submenu | Workflow | Required inputs |
|---------|----------|-----------------|
| 1. img2img | `workflows/base/img2img/workflow.json` | source image |
| 2. Inpainting | `workflows/base/inpainting/workflow.json` | source image + mask |
| 3. Outpainting | `workflows/base/outpainting/workflow.json` | source image + expansion pixels |

The submenu calls `list_inputs.py`, `validate_capabilities.py`, and `prepare_workflow.py` — validation logic is not duplicated in the notebook. Preparation stages inputs into ComfyUI `input/` automatically.

Persistent Drive inputs: `/content/drive/MyDrive/AI_Studio/inputs/images/` and `.../masks/`.

Prepared workflows: `/content/ai-studio-runtime/workflows/` (ephemeral).

## Bootstrap Scripts (callable from notebook)

Run **Repository Sync** first (clones/pulls repo from GitHub), then Cell 3b:

```python
# Cell 3b — Repository Bootstrap & Validation
!python core/scripts/bootstrap_repo.py
!python core/scripts/validate_environment.py
!python core/scripts/validate_paths.py
!python core/scripts/validate_manifests.py
!python core/scripts/list_workflows.py
```

After ComfyUI install:

```python
!python core/scripts/check_nodes.py
!python core/scripts/verify_models.py
!python core/scripts/sync_outputs.py --dry-run
```

## Runtime Platform (Cell 3c)

Cell 3c runs `runtime_report.py` for structured health across notebook, repo, Drive, engines, registries, and GPU.

All scripts use standard library Python only. They are safe to run repeatedly and do not download models or install software.

## Configuration Manifests

The notebook reads path and registry data from `configs/`:

| Manifest | Purpose |
|----------|---------|
| `configs/paths/colab_paths.json` | Colab runtime and Drive path mappings |
| `configs/models/model_registry.json` | Model categories and requirements |
| `configs/nodes/node_registry.json` | Custom node repos and install metadata |
| `configs/presets/default_generation_presets.json` | Starter generation parameters |
| `configs/workflows/workflow_registry.json` | Planned workflow index |

The **GitHub repository** is the source of truth for the notebook, workflows, configs, scripts, and documentation. Google Drive holds persistent runtime assets (models, outputs) that are too large for Git.

## Opening the Canonical Notebook in Colab

1. Browse to the notebook on GitHub: `colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb`
2. Click **Open in Colab**, or use the direct link:

   **https://colab.research.google.com/github/morecolorfulthanHD/ai-studio-colab/blob/main/colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb**

3. Run **Repository Sync** — it clones or pulls into `/content/ai-studio-colab`
4. Continue with Cells 3b and 3c

## Old Drive Copy Fallback

If you open an older notebook saved on Drive:

- **Repository Sync** still pulls the latest repo **code** from GitHub
- The notebook **cells** you are running come from the Drive file, which may be stale
- Switch to the GitHub Colab link above periodically, or stop using the Drive copy

## Design Rules

1. **One notebook** — Never create a second control panel notebook.
2. **Enhance, don't replace** — Add cells and functions to the existing notebook.
3. **Repo over notebook** — Logic that can live in `core/scripts/` or `configs/` should not be embedded in notebook cells.
4. **Explicit errors** — No silent failures; match the notebook's existing design goals.
5. **Disposable runtime** — Assume `/content/` is wiped each session; persist via Drive.

## Persistent Drive Layout

Per `configs/paths/colab_paths.json`:

```
/content/drive/MyDrive/AI_Studio/
├── models/shared/     # persistent model weights
├── outputs/           # synced generation outputs
├── datasets/          # reference datasets (optional)
└── references/        # reference images (optional)
```

Drive does **not** host the canonical notebook. The `drive_workflows` path in `colab_paths.json` is reserved for optional local backups only.

## Related Documentation

- [architecture.md](architecture.md) — Full system design
- [installation.md](installation.md) — Setup procedures
- [roadmap.md](roadmap.md) — Phase plan
