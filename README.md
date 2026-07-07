# AI Studio Colab

A general-purpose, version-controlled AI Studio for high-end image generation, environment generation, character consistency, and video generation.

**Current phase:** Epic 2 Package 1 — runtime platform foundation (`core/runtime/`, health reporting, install planners).

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
| **GitHub** | Version-controlled source of truth for code, configs, workflows, docs | Permanent |
| **Cursor** | Local development and editing | — |
| **Google Colab** | Disposable GPU runtime for generation | Session only |
| **Google Drive** | Models, outputs, workflow backups | Permanent |
| **ComfyUI** | Primary node-based workflow engine | Runtime install at `/content/ComfyUI` |
| **A1111** | Secondary WebUI for select pipelines | Runtime install at `/content/A1111` |
| **Workflows** | Reusable ComfyUI JSON assets in `workflows/` | Git-managed |
| **Use cases** | Validation datasets (e.g., Zara Morrison) | Git + Drive |

## Canonical Control Panel

Launch AI Studio via the single official notebook:

**[`colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb`](colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb)**

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
│   └── workflows/workflow_registry.json
├── assets/                       # Model weight storage (gitignored binaries)
├── workflows/                    # Composable workflow definitions
├── use_cases/                    # Project validation datasets
├── output/                       # Generated artifacts (gitignored)
└── tests/
```

## Quick Start (Colab)

1. Open [`colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb`](colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb) in Google Colab.
2. Select a GPU runtime.
3. Clone or sync this repository into the runtime.
4. Run bootstrap validation:

```bash
python core/scripts/bootstrap_repo.py
python core/scripts/validate_environment.py
python core/scripts/validate_manifests.py
```

5. Follow the notebook cells for Drive mount, ComfyUI launch, and generation.

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
| `core/scripts/sync_outputs.py` | Copy latest ComfyUI output to Drive |

## Documentation

| Document | Description |
|----------|-------------|
| [colab-control-panel.md](docs/colab-control-panel.md) | Canonical notebook and orchestration design |
| [runtime-platform.md](docs/runtime-platform.md) | Runtime lifecycle, registry flow, health model |
| [architecture.md](docs/architecture.md) | System design and module boundaries |
| [installation.md](docs/installation.md) | Setup and update procedures |
| [workflow-guide.md](docs/workflow-guide.md) | Workflow categories and composition |
| [roadmap.md](docs/roadmap.md) | Phased development plan |
| [troubleshooting.md](docs/troubleshooting.md) | Common issues and diagnostics |

## Immediate Next Steps

1. Run Cell 3c (`runtime_report.py`) in Colab after bootstrap validation.
2. Epic 2 Package 2: execute install plans (nodes, models) from registry planners.
3. Create first workflow JSON: `workflows/base/txt2img/workflow.json`.
4. Wire notebook Cell 9 to runtime manager install execution.
5. Mark `sd15_checkpoint` as `active` after first successful generation.

## Development Philosophy

- **Incremental** — Each workflow is production-tested before the next begins.
- **Composable** — Small building blocks over monolithic graphs.
- **Reproducible** — Version-controlled configs, documented dependencies, pinned settings.
- **General-purpose** — No project-specific logic in core or base workflows.

## License

TBD.
