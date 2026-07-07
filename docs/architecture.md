# Architecture

This document describes the modular architecture of AI Studio Colab. The design prioritizes reusability, reproducibility, and clear separation between platform code, configuration, workflows, and project-specific use cases.

## Design Principles

1. **General-purpose core** — Core engines and base workflows contain no project-specific logic.
2. **Composable workflows** — Each workflow is a small, documented building block that pipelines can assemble.
3. **Configuration over hardcoding** — Paths, model names, and presets live in `configs/`, not inside workflow JSON.
4. **Shared resources** — Models and custom nodes are centralized to avoid duplication across engines.
5. **Git-managed structure** — Folder layout, configs, and workflow definitions are version-controlled; large binaries are gitignored.
6. **Validation via use cases** — Production projects (e.g., Zara Morrison) live in `use_cases/` and consume platform workflows unchanged.

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Launch Layer                              │
│  colab/notebooks/  ·  colab/launch/  ·  colab/utilities/        │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│                        Core Layer                                │
│  core/comfyui/  ·  core/automatic1111/  ·  core/scripts/        │
│  core/runtime/  ·  core/shared_models/  ·  core/shared_nodes/     │
│  core/storage/                                                   │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│                     Configuration Layer                          │
│  configs/models/  ·  configs/nodes/  ·  configs/paths/           │
│  configs/presets/  ·  configs/workflows/  ·  configs/assets/      │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│                      Workflow Layer                              │
│  workflows/base/  ·  workflows/controlnet/  ·  workflows/        │
│  extraction/  ·  workflows/reference/  ·  workflows/animation/   │
│  workflows/pipelines/                                            │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│                      Use Case Layer                              │
│  use_cases/<project>/  — prompts, references, validation only    │
└─────────────────────────────────────────────────────────────────┘
```

## Layer Descriptions

### Launch Layer (`colab/`)

Entry points for running the studio, primarily Google Colab notebooks and helper scripts.

| Path | Purpose |
|------|---------|
| `colab/notebooks/` | Canonical control panel and workflow notebooks |
| `colab/launch/` | Environment bootstrap and service startup scripts |
| `colab/utilities/` | Colab-specific helpers (Drive mount, GPU checks, path setup) |

The canonical launcher is [`colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb`](../colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb). This is the **only** control panel notebook — do not duplicate it. See [colab-control-panel.md](colab-control-panel.md).

### Core Layer (`core/`)

Engine installations and shared infrastructure.

| Path | Purpose |
|------|---------|
| `core/comfyui/` | ComfyUI installation, custom node management, launch scripts |
| `core/automatic1111/` | A1111 WebUI installation and extensions |
| `core/shared_models/` | Symlinks or junctions pointing to `assets/` model directories |
| `core/shared_nodes/` | Custom node repos shared across engines where applicable |
| `core/storage/` | Runtime cache, temp files, and upload staging |
| `core/scripts/` | Bootstrap, validation, runtime report, batch utilities |
| `core/runtime/` | Registry loader, health model, runtime manager, asset manager, session state |

Bootstrap scripts are callable from the control panel notebook. The **runtime platform** (`core/runtime/`) provides structured health reporting and future orchestration hooks. See [runtime-platform.md](runtime-platform.md).

Both ComfyUI and A1111 read models from `assets/` or Drive-backed paths via `configs/paths/colab_paths.json` rather than maintaining duplicate weight copies.

### Configuration Layer (`configs/`)

Centralized, version-controlled settings that workflows reference by key.

| Path | Purpose |
|------|---------|
| `configs/models/model_registry.json` | Model categories, intended paths, required-for workflows |
| `configs/nodes/node_registry.json` | Custom node repos, install mode, required-for workflows |
| `configs/paths/colab_paths.json` | Colab runtime and Google Drive path mappings |
| `configs/presets/default_generation_presets.json` | Named parameter sets (sampler, steps, CFG, resolution) |
| `configs/workflows/workflow_registry.json` | Workflow index with status, dependencies, and paths |
| `configs/assets/asset_registry.json` | Unified cross-cutting asset inventory |

See [asset-registry.md](asset-registry.md) for how asset, model, and workflow registries relate.

### Asset Layer (`assets/`)

Physical storage for model weights. Binary files are gitignored; README files document what belongs in each folder.

### Workflow Layer (`workflows/`)

ComfyUI workflow JSON files organized by capability. See [workflow-guide.md](workflow-guide.md) for the full taxonomy and composition rules.

### Use Case Layer (`use_cases/`)

Project-specific content only:

- Prompt libraries
- Reference images and environment captures
- Test outputs for validation
- Project documentation

Use cases **import** platform workflows; they do not fork or modify them.

## Engine Strategy

### ComfyUI (Primary)

ComfyUI is the primary workflow engine. All new workflows are authored as ComfyUI graphs first. Benefits:

- Native node composition and sub-graph reuse
- Explicit data flow for debugging and reproducibility
- Strong ecosystem for ControlNet, IPAdapter, AnimateDiff, and video nodes

### Automatic1111 (Secondary)

A1111 is retained for workflows where the WebUI ecosystem offers mature extensions not yet replicated in ComfyUI, and for rapid prototyping. Configuration mirrors ComfyUI model paths via `configs/paths/`.

## Model Family Roadmap

| Family | Status | Notes |
|--------|--------|-------|
| SD 1.5 | Phase 1 | Initial base workflows |
| SDXL | Future | Parallel workflow tree under `workflows/base/` |
| Flux | Future | New preset and model config entries |
| SVD | Phase 6 | Video-specific assets in `assets/checkpoints/` |

## Shared Node Dependencies

The following custom node packs are first-class dependencies (configured in `configs/nodes/`):

- ControlNet Aux preprocessors
- ComfyUI Impact Pack
- WAS Node Suite
- AnimateDiff nodes
- ReActor / InsightFace integration nodes

Node versions are pinned in config files to ensure reproducibility across environments.

## Runtime Model

| Storage | Role | Lifetime |
|---------|------|----------|
| **Git repository** | Source of truth for workflows, configs, scripts, docs | Permanent |
| **Google Drive** (`/content/drive/MyDrive/AI_Studio`) | Persistent models, outputs, workflow backups | Permanent |
| **Colab runtime** (`/content/ComfyUI`, `/content/A1111`) | Installed engines and session cache | Disposable per session |
| **Repo `output/`** | Local/dev generated artifacts | Gitignored |

The control panel notebook orchestrates the boundary between disposable runtime and persistent Drive storage.

## Data Flow

```
Inputs (prompts, reference images, control maps)
        │
        ▼
  Workflow JSON  ◄── configs/presets/ (parameters)
        │          ◄── configs/models/  (checkpoint selection)
        │          ◄── configs/paths/   (file locations)
        │          ◄── configs/workflows/ (workflow index)
        ▼
  ComfyUI / A1111 execution  (Colab runtime)
        │
        ▼
  /content/ComfyUI/output  ──sync──►  Drive/outputs/
        │
        ▼
  output/  (local dev artifacts)
```

## Extension Points

Future capabilities plug in at defined boundaries:

| Capability | Extension Location |
|------------|-------------------|
| New model family | `configs/models/`, `assets/checkpoints/` |
| New preprocessor | `workflows/extraction/`, `configs/nodes/` |
| New pipeline | `workflows/pipelines/` |
| New production project | `use_cases/<name>/` |
| Automation / batching | Phase 7 — `core/scripts/`, `colab/utilities/` |
| Runtime orchestration | `core/runtime/`, `core/scripts/runtime_report.py` |
| Additional engines | `configs/engines/` (future), `core/a1111/`, inference hooks in `RuntimeManager` |
| Container / bare-metal deploy | Docker / Windows / Linux hooks via `extension_points()` (future) |

## What Does Not Belong Here

- Project-specific character logic in `core/` or `workflows/`
- Monolithic all-in-one workflow files
- Hardcoded absolute paths outside `configs/paths/`
- Duplicate model copies per engine
- AIMDO or AIMDO-related dependencies (explicitly excluded)
