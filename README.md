# AI Studio Colab

A general-purpose, version-controlled AI Studio for high-end image generation, environment generation, character consistency, and video generation.

**Current phase:** Production Package 4 — image editing foundation (img2img, inpainting, outpainting).

## What This Is

A modular platform combining ComfyUI, Automatic1111, ControlNet, AnimateDiff, SVD, ReActor, and related tooling into composable, Git-managed workflows. Any future project can adopt the platform without modification.

## What This Is Not

- Not a single-project repository (Zara Morrison is a validation use case, not the architecture center)
- Not a model hosting service (weights live on Drive or local `assets/`, not in Git)
- Not a monolithic workflow collection (workflows are small, composable building blocks)

## How the Pieces Fit Together

```
┌─────────────┐     clone/pull      ┌──────────────────────────────┐
│   GitHub    │ ──────────────────► │  ai-studio-colab (repo)        │
│  (remote)   │                     │  configs · workflows · scripts│
└─────────────┘                     └──────────────┬───────────────┘
                                                   │
┌─────────────┐     edit/develop    ┌──────────────▼───────────────┐
│   Cursor    │ ◄──────────────────► │  Local or Colab workspace    │
│    (IDE)    │                     └──────────────┬───────────────┘
└─────────────┘                                    │
                     ┌─────────────────────────────┼─────────────────────────────┐
                     ▼                             ▼                             ▼
           ┌─────────────────┐          ┌─────────────────┐          ┌─────────────────┐
           │  Google Colab   │          │  Google Drive   │          │ ComfyUI / A1111 │
           │  (disposable    │          │  (persistent    │          │ (runtime tools, │
           │   GPU compute)  │          │   storage)      │          │  reinstalled)   │
           └────────┬────────┘          └─────────────────┘          └─────────────────┘
                    │
                    ▼
     colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb
                    │
                    ▼
              core/scripts/  ·  configs/  ·  workflows/
```

| Component | Role | Persistence |
|-----------|------|-------------|
| **GitHub** | **Canonical source of truth** — notebook, scripts, configs, workflows, docs | Permanent |
| **Cursor** | Local development and editing | — |
| **Google Colab** | Disposable GPU runtime for generation | Session only |
| **Google Drive** | Persistent models, outputs, datasets, references, checkpoints | Permanent |
| **ComfyUI** | Primary node-based workflow engine | Runtime install at `/content/ComfyUI` |
| **A1111** | Secondary WebUI for select pipelines | Runtime install at `/content/A1111` |
| **Workflows** | Reusable ComfyUI JSON assets in `workflows/` | Git-managed |
| **Use cases** | Validation datasets (e.g., Zara Morrison) | Git + Drive |

## Canonical Control Panel

The **canonical notebook lives in this GitHub repository** — not on Google Drive.

**[`colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb`](colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb)**

Open it directly in Colab from GitHub:

**https://colab.research.google.com/github/morecolorfulthanHD/ai-studio-colab/blob/main/colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb**

Google Drive is persistent storage for models and outputs only. A notebook file saved on Drive, if any, is a convenience copy or launcher — not the source of truth. The **Repository Sync** cell clones or pulls the latest repo from GitHub into `/content/ai-studio-colab` each session.

Do not create duplicate launcher notebooks. See [docs/colab-control-panel.md](docs/colab-control-panel.md).

## Repository Layout

```
ai-studio-colab/
├── README.md
├── docs/                         # Architecture, installation, guides
├── colab/
│   ├── notebooks/                # Canonical control panel notebook
│   ├── launch/                   # Bootstrap and startup scripts (future)
│   └── utilities/                # Colab-specific helpers (future)
├── core/
│   ├── runtime/                  # Registry loader, health, runtime manager
│   ├── comfyui/                  # ComfyUI install scripts + planners
│   ├── automatic1111/            # A1111 install scripts (future)
│   └── scripts/                  # Bootstrap, validation, runtime report
├── configs/
│   ├── paths/colab_paths.json    # Colab + Drive path mappings
│   ├── models/model_registry.json
│   ├── nodes/node_registry.json
│   ├── presets/default_generation_presets.json
│   ├── workflows/workflow_registry.json
│   ├── assets/asset_registry.json
│   └── capabilities/capability_registry.json
├── assets/                       # Model weight storage (gitignored binaries)
├── workflows/                    # Composable workflow definitions
├── use_cases/                    # Project validation datasets
├── output/                       # Generated artifacts (gitignored)
└── tests/
```

## Quick Start (Colab)

1. Open the canonical notebook from GitHub in Colab (link above) or browse to `colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb` on GitHub → **Open in Colab**.
2. Select a GPU runtime.
3. Run cells through **Repository Sync** and bootstrap (Cells 1–3c).
4. Run `control_panel()` and choose **1. Launch** — pick `safe`, `minimal`, or `full`.
5. Follow on-screen ComfyUI URL and base txt2img workflow guidance.

### Launch Modes

| Mode | ComfyUI | Custom Nodes | SD1.5 Check | txt2img Guidance |
|------|---------|--------------|-------------|------------------|
| **safe** | install + launch | skipped | yes (warn if missing) | no |
| **minimal** | install + launch | skipped | yes (warn if missing) | yes |
| **full** | install + launch | install registered stable nodes | yes (warn if missing) | yes |

Expected SD1.5 path:

`/content/drive/MyDrive/AI_Studio/models/shared/checkpoints/sd15.safetensors`

Base txt2img workflow:

`/content/ai-studio-colab/workflows/base/txt2img/workflow.json`

After generating an image:

```bash
python core/scripts/sync_outputs.py --dry-run
python core/scripts/sync_outputs.py
```

### Image Editing (Package 4)

Implemented capabilities: **img2img**, **inpainting**, **outpainting**.

Persistent Drive inputs:

```
/content/drive/MyDrive/AI_Studio/inputs/images/
/content/drive/MyDrive/AI_Studio/inputs/masks/
```

Prepare ephemeral runtime workflows (canonical JSON never modified; inputs staged into ComfyUI/input):

```bash
python core/scripts/list_inputs.py
python core/scripts/prepare_workflow.py --workflow img2img --input /path/to/source.png
python core/scripts/prepare_workflow.py --workflow inpainting --input /path/to/source.png --mask /path/to/mask.png
python core/scripts/prepare_workflow.py --workflow outpainting --input /path/to/source.png --left 256 --right 256
python core/scripts/prepare_workflow.py --workflow img2img --input /path/to/source.png --dry-run
python core/scripts/verify_generation.py --workflow img2img --summary
```

`--dry-run` is fully read-only (no directories created, no copies). Staged-file reuse requires identical SHA-256 content, not just matching filename and size.

Inpainting requires a dedicated checkpoint at:

`/content/drive/MyDrive/AI_Studio/models/shared/checkpoints/512-inpainting-ema.safetensors`

`sd15.safetensors` is not sufficient for reliable base inpainting object replacement. No automatic download occurs; place the model manually and review licensing/source before use.

**Dogfooding sequence:** Drive inputs → `list_inputs.py` → `prepare_workflow.py` (stages into `/content/ComfyUI/input`) → import prepared workflow → generate → `sync_outputs.py` → `verify_generation.py`.

**Implementation readiness** (ComfyUI + SD1.5 + valid workflow) is computed separately from **execution input readiness** (whether the user has selected source/mask files). A capability can be `READY` before any Drive input is placed.

Control panel: `control_panel()` → **7. Image Editing**.

Dogfooding: [docs/dogfooding/img2img-checklist.md](docs/dogfooding/img2img-checklist.md), [inpainting](docs/dogfooding/inpainting-checklist.md), [outpainting](docs/dogfooding/outpainting-checklist.md).

## Bootstrap Scripts

| Script | Purpose |
|--------|---------|
| `core/scripts/bootstrap_repo.py` | Validate repo structure; document git sync hook |
| `core/scripts/validate_environment.py` | Python, Colab, Drive, GPU checks |
| `core/scripts/validate_paths.py` | Validate Colab/Drive/repo paths |
| `core/scripts/validate_manifests.py` | Validate JSON manifests under `configs/` |
| `core/scripts/list_workflows.py` | List workflow JSON files by category |
| `core/scripts/runtime_report.py` | Unified runtime health report (human + JSON) |
| `core/scripts/check_nodes.py` | Report installed vs. missing custom nodes |
| `core/scripts/verify_models.py` | Report present vs. missing model files |
| `core/scripts/validate_assets.py` | Asset registry validation |
| `core/scripts/validate_capabilities.py` | Capability readiness validation |
| `core/scripts/sync_outputs.py` | Copy latest ComfyUI output to Drive (`--dry-run`) |
| `core/scripts/dogfood_core_runtime.py` | Read-only dogfooding checks (PASS/WARN/FAIL) |
| `core/scripts/verify_generation.py` | Read-only generation evidence (`--summary`, `--json`) |

## Dogfooding (Sprint 1)

Validate core runtime + base txt2img in Colab before adding advanced workflows:

- Checklist: [docs/dogfooding/core-runtime-txt2img-checklist.md](docs/dogfooding/core-runtime-txt2img-checklist.md)
- Support script: `python core/scripts/dogfood_core_runtime.py`

## Documentation

| Document | Description |
|----------|-------------|
| [colab-control-panel.md](docs/colab-control-panel.md) | Canonical notebook and orchestration design |
| [asset-registry.md](docs/asset-registry.md) | Unified asset inventory and registry relationships |
| [capability-platform.md](docs/capability-platform.md) | Capability abstraction and readiness evaluation |
| [runtime-platform.md](docs/runtime-platform.md) | Runtime lifecycle, registry flow, health model |
| [architecture.md](docs/architecture.md) | System design and module boundaries |
| [installation.md](docs/installation.md) | Setup and update procedures |
| [workflow-guide.md](docs/workflow-guide.md) | Workflow categories and composition |
| [roadmap.md](docs/roadmap.md) | Phased development plan |
| [troubleshooting.md](docs/troubleshooting.md) | Common issues and diagnostics |
| [dogfooding/core-runtime-txt2img-checklist.md](docs/dogfooding/core-runtime-txt2img-checklist.md) | Colab validation checklist (Sprint 1) |

## Immediate Next Steps

1. Run `control_panel()` → **1. Launch** → choose `minimal` for first image readiness.
2. Confirm SD1.5 at `/content/drive/MyDrive/AI_Studio/models/shared/checkpoints/sd15.safetensors`.
3. Import `workflows/base/txt2img/workflow.json` in ComfyUI and queue a baseline prompt.
4. Copy latest output with `python core/scripts/sync_outputs.py`.
5. Re-run `python core/scripts/runtime_report.py --summary` and `python core/scripts/verify_generation.py --summary` to confirm txt2img readiness and generation evidence.

## Base Generation Workflow

First production workflow:

- Path: `workflows/base/txt2img/workflow.json`
- Engine: ComfyUI core nodes only (no custom-node dependency)
- Defaults: SD 1.5 checkpoint (`sd15.safetensors`), prompt and negative prompt included
- Output: saved image via `SaveImage`

## Development Philosophy

- **Incremental** — Each workflow is production-tested before the next begins.
- **Composable** — Small building blocks over monolithic graphs.
- **Reproducible** — Version-controlled configs, documented dependencies, pinned settings.
- **General-purpose** — No project-specific logic in core or base workflows.

## License

TBD.
