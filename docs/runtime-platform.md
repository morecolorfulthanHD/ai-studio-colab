# Runtime Platform

How AI Studio evolves from a static repository into a registry-driven runtime platform.

## Vision

The control panel notebook becomes an **orchestrator** that can answer:

> *Is my AI Studio healthy?*

It does this by loading manifests, inspecting the runtime environment, and returning structured health objects — not ad-hoc print statements scattered across cells.

## Architecture

```
colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb
        │
        ▼
core/scripts/runtime_report.py
        │
        ▼
core/runtime/runtime_manager.py
        ├── registry_loader.py   ◄── configs/**/*.json
        ├── asset_manager.py     ◄── configs/assets/asset_registry.json
        ├── capability_manager.py◄── configs/capabilities/capability_registry.json
        ├── runtime_health.py
        └── runtime_state.py
        │
        ├── core/comfyui/install_nodes.py   (plan only)
        ├── core/comfyui/install_models.py (plan only)
        └── core/a1111/install.py          (plan only)
```

## Runtime Lifecycle

| Phase | What Happens | Status |
|-------|--------------|--------|
| 1. Bootstrap | Clone repo, mount Drive, validate structure | Epic 1 ✓ |
| 2. Health check | `runtime_report.py` + `validate_assets.py` + `validate_capabilities.py` / Cell 3c | Epic 2 Pkg 1–3 ✓ |
| 3. Plan installs | Install planners emit dry-run steps | Epic 2 Pkg 1 ✓ |
| 4. Execute installs | ComfyUI + node execution scripts available with explicit `--execute` | Production Pkg 1 ✓ |
| 5. Launch engines | ComfyUI / A1111 via notebook or launch scripts | Partial |
| 6. Run workflows | Load workflow JSON, execute pipeline | Deferred |

## Registry Flow

1. `RegistryLoader` discovers every `*.json` file under `configs/`
2. Known registries are exposed as typed lists (`models`, `nodes`, `workflows`, `presets`, `assets`, `capabilities`)
3. Unknown future manifests remain in `bundle.manifests` without code changes
4. Paths resolve through `configs/paths/colab_paths.json` — no hardcoded `/content/` in runtime code

```python
from core.runtime.registry_loader import RegistryLoader

bundle = RegistryLoader().load_all()
comfyui_path = bundle.path("comfyui_runtime")
models = bundle.models
```

## Validation Flow

### Structured health (`runtime_health.py`)

Each component returns a `HealthCheck`:

| Field | Description |
|-------|-------------|
| `component` | e.g. `drive`, `comfyui`, `model_registry` |
| `status` | `ok`, `warn`, `fail`, `unknown`, `planned` |
| `message` | Human-readable summary |
| `details` | Machine-readable dict |

Components checked:

- Notebook (canonical path exists)
- Repository (required directories)
- Google Drive (`drive_root`)
- ComfyUI installation
- A1111 installation
- Workflow registry (registered vs on-disk JSON)
- Node registry (installed vs missing)
- Model registry (present vs planned)
- **Asset registry** (unified inventory — present / missing / planned)
- **Capability registry** (ready / partial / unavailable / blocked)
- GPU (`nvidia-smi`)

### Unified report (`runtime_report.py`)

```bash
python core/scripts/runtime_report.py           # human-readable
python core/scripts/runtime_report.py --summary # one line
python core/scripts/runtime_report.py --json    # full structured JSON
python core/scripts/validate_assets.py --summary
python core/scripts/validate_capabilities.py --summary
```

### Notebook integration

**Cell 3c — Runtime Platform Health** runs `runtime_report.py` and summary checks for assets and capabilities after Cell 3b bootstrap validation.

## Runtime State

`RuntimeState` holds session metadata in memory (not auto-persisted yet):

- `installed_models`, `installed_nodes`
- `last_runtime`, `last_launch_mode`, `last_workflow`
- `platform_version`, `environment`

Future packages will persist state to Drive under `AI_Studio/settings/` or similar.

## Install Planning (No Execution Yet)

Install scripts parse registries and print **execution plans** with `--dry-run` (default). Node execution is now available with explicit `--execute`:

| Script | Plans |
|--------|-------|
| `core/comfyui/install_nodes.py` | `git_clone`, `pip_requirements`, `skip` (+ execute mode) |
| `core/comfyui/install_models.py` | `validate_missing`, `skip`, `verify` (no downloads) |
| `core/a1111/install.py` | `git_clone`, `symlink`, `pip_bootstrap` |

Model downloads remain intentionally deferred.

## Future Orchestration

`RuntimeManager` exposes extension hooks without implementing them:

| Hook | Purpose |
|------|---------|
| `plan_comfyui_install()` | Aggregate node + model plans |
| `plan_a1111_install()` | A1111 clone + symlink plan |
| `capability_summary()` | Computed user-facing functionality readiness |
| `extension_points()` | Document future engines and deployments |

### Readiness vs evidence

- **Readiness** answers whether a capability can run now (runtime, workflow, required assets, required nodes).
- **Evidence** answers whether a successful generation has already been observed (local output and optional Drive sync).
- Base `txt2img`, `img2img`, `inpainting`, and `outpainting` can be `READY` with evidence `NOT YET VERIFIED` on a fresh runtime before the first image is generated.
- **Implementation readiness** covers ComfyUI runtime, SD1.5, workflow validation, and required nodes.
- **Execution input readiness** (`execution_input_status`) reports whether Drive/runtime source images and masks are available; it does not downgrade installed capability status when inputs are not yet selected.
- Drive evidence requires an exact byte-size match. When `sync_outputs.py` writes a collision-safe timestamped filename, `verify_generation.py` recognizes that derivative as synchronized evidence when sizes match.

### CLI repository resolution

User-facing scripts under `core/scripts/` resolve the repository root from the invoked script path (`core/runtime/repo_paths.py`), so absolute-path commands work without changing the notebook working directory first.

### Required vs optional node health

Node health distinguishes required bootstrap nodes from optional workflow packs. Missing optional nodes (for example `ComfyUI-ReActor`) produce warnings but do not block base txt2img or image-editing readiness.

### Image editing inputs and preparation

| Path | Purpose |
|------|---------|
| `drive_inputs/images/` | Persistent source images (`.png`, `.jpg`, `.jpeg`, `.webp`) |
| `drive_inputs/masks/` | Inpainting masks |
| `comfyui_runtime/input/` | Ephemeral staged inputs copied by `prepare_workflow.py` (SHA-256 content match before reuse) |
| `runtime_workflows/` | Ephemeral prepared workflow JSON |

`prepare_workflow.py` validates inputs, stages copies into ComfyUI `input/` with collision-safe naming, patches LoadImage/mask/pad nodes in a runtime copy, and never modifies canonical repository workflow JSON. Workflow validators also require connected execution graphs, not just node presence.

### Planned extension points

| Category | Examples |
|----------|----------|
| Model families | Flux, SDXL (registry entries only today) |
| Engines | ComfyUI, A1111, future inference servers |
| Deployment | Docker container, Windows local, Linux server |
| Persistence | Drive-backed runtime state, version pinning |

Add a new JSON manifest under `configs/` → `RegistryLoader` picks it up automatically. Add typed accessors to `RegistryBundle` only when a manifest becomes first-class.

## What Is Deferred

- Executing install plans (downloads, git clones from planners)
- Production workflow JSON
- OpenPose, SVD, ReActor, AnimateDiff, reference-lock workflows
- Auto-persisting `RuntimeState`
- Replacing notebook Cell 9 installers with runtime manager execution

## Related Documentation

- [architecture.md](architecture.md) — full system design
- [installation.md](installation.md) — setup procedures
- [capability-platform.md](capability-platform.md) — capability abstraction layer
- [colab-control-panel.md](colab-control-panel.md) — notebook cells
- [core/runtime/README.md](../core/runtime/README.md) — module reference
