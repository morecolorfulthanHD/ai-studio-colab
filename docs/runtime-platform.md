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
| 2. Health check | `runtime_report.py` / Cell 3c | Epic 2 Pkg 1 ✓ |
| 3. Plan installs | Install planners emit dry-run steps | Epic 2 Pkg 1 ✓ |
| 4. Execute installs | Planners execute plans (future) | Deferred |
| 5. Launch engines | ComfyUI / A1111 via notebook or launch scripts | Partial |
| 6. Run workflows | Load workflow JSON, execute pipeline | Deferred |

## Registry Flow

1. `RegistryLoader` discovers every `*.json` file under `configs/`
2. Known registries are exposed as typed lists (`models`, `nodes`, `workflows`, `presets`)
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
- GPU (`nvidia-smi`)

### Unified report (`runtime_report.py`)

```bash
python core/scripts/runtime_report.py           # human-readable
python core/scripts/runtime_report.py --summary # one line
python core/scripts/runtime_report.py --json    # full structured JSON
```

### Notebook integration

**Cell 3c — Runtime Platform Health** runs `runtime_report.py` after Cell 3b bootstrap validation.

## Runtime State

`RuntimeState` holds session metadata in memory (not auto-persisted yet):

- `installed_models`, `installed_nodes`
- `last_runtime`, `last_launch_mode`, `last_workflow`
- `platform_version`, `environment`

Future packages will persist state to Drive under `AI_Studio/settings/` or similar.

## Install Planning (No Execution Yet)

Install scripts parse registries and print **execution plans** with `--dry-run` (default):

| Script | Plans |
|--------|-------|
| `core/comfyui/install_nodes.py` | `git_clone`, `pip_requirements`, `skip` |
| `core/comfyui/install_models.py` | `download_or_copy`, `skip`, `verify` |
| `core/a1111/install.py` | `git_clone`, `symlink`, `pip_bootstrap` |

Future installers will execute these plans step-by-step with logging and rollback hooks.

## Future Orchestration

`RuntimeManager` exposes extension hooks without implementing them:

| Hook | Purpose |
|------|---------|
| `plan_comfyui_install()` | Aggregate node + model plans |
| `plan_a1111_install()` | A1111 clone + symlink plan |
| `extension_points()` | Document future engines and deployments |

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
- [colab-control-panel.md](colab-control-panel.md) — notebook cells
- [core/runtime/README.md](../core/runtime/README.md) — module reference
