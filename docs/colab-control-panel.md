# Colab Control Panel

The canonical launcher for AI Studio Colab is a single Google Colab notebook:

**`colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb`**

This notebook is the official control panel. Do not duplicate it. Future improvements should enhance this notebook rather than replace it.

## Role in the Architecture

```
GitHub (source of truth)          Google Drive (persistent storage)
        │                                    │
        │  clone / pull                      │  models, outputs, backups
        ▼                                    ▼
┌───────────────────────────────────────────────────────────────┐
│         AI_Studio_Control_Panel_Colab.ipynb                   │
│  mount Drive · verify GPU · validate paths · sync repo        │
│  launch ComfyUI · launch A1111 · workflow menus               │
└───────────────────────────┬───────────────────────────────────┘
                            │
            ┌───────────────┼───────────────┐
            ▼               ▼               ▼
      /content/ComfyUI  /content/A1111   core/scripts/
      (runtime)         (runtime)        (validation helpers)
```

| Layer | Location | Persistence |
|-------|----------|-------------|
| **Repository** | Cloned to `/content/` or local disk | Git-managed configs, workflows, scripts, docs |
| **Colab runtime** | `/content/ComfyUI`, `/content/A1111` | Ephemeral — reinstalled each session |
| **Google Drive** | `/content/drive/MyDrive/AI_Studio` | Persistent models, outputs, workflow backups |
| **Bootstrap scripts** | `core/scripts/` | Called from notebook cells for validation |

## What the Notebook Should Eventually Do

The control panel will become a self-updating AI Studio orchestrator:

| Capability | Status | Helper |
|------------|--------|--------|
| Mount Google Drive | In notebook (Cell 2) | — |
| Verify GPU | In notebook (Cell 1) | `validate_environment.py` |
| Verify paths | Cell 3b | `validate_paths.py` |
| Repo bootstrap validation | Cell 3b | `bootstrap_repo.py`, `validate_manifests.py`, `list_workflows.py` |
| Sync / pull repo | Planned | `bootstrap_repo.py` (git hook documented) |
| Launch ComfyUI | In notebook (Cell 10) | `core/comfyui/install.sh` (Cell 9 integration planned) |
| Launch A1111 | In notebook (Cell 10) | `colab/launch/` (future) |
| Validate models | Available | `verify_models.py` |
| Validate nodes | Available | `check_nodes.py` |
| Install missing models/nodes | Planned | driven by registries + notebook managers |
| Expose workflow menus | Planned | `list_workflows.py` + `workflow_registry.json` |
| Sync outputs | Available | `sync_outputs.py` |
| Runtime health | Cell 3c | `runtime_report.py` |
| Backup / restore workflows | Planned | Drive path `drive_workflows` |

## Bootstrap Scripts (callable from notebook)

Cell 3b runs these automatically after Drive mount:

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

The repository is the **source of truth** for workflows, configs, scripts, and documentation. Drive holds runtime artifacts that are too large or session-specific for Git.

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
└── workflows/         # workflow backups (future)
```

## Related Documentation

- [architecture.md](architecture.md) — Full system design
- [installation.md](installation.md) — Setup procedures
- [roadmap.md](roadmap.md) — Phase plan
