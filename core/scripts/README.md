# Core Scripts

Cross-engine utility scripts for bootstrap, validation, and batch processing.

**All scripts use standard library Python only.** Safe to run in Colab without additional dependencies.

## Bootstrap & Validation (Phase 1)

| Script | Purpose | Installs? |
|--------|---------|-----------|
| `bootstrap_repo.py` | Validate repo structure; document git sync hook | No |
| `validate_environment.py` | Python, Colab, Drive, GPU checks | No |
| `validate_paths.py` | Validate Colab/Drive/repo paths from manifest | No |
| `validate_manifests.py` | Validate JSON schemas under `configs/` | No |
| `list_workflows.py` | List workflow JSON files by category | No |
| `sync_outputs.py` | Copy latest ComfyUI output to Drive (`--dry-run`) | No |

## Runtime Verification (Phase 1b)

| Script | Purpose | Installs? |
|--------|---------|-----------|
| `check_nodes.py` | Compare `custom_nodes/` vs. `configs/nodes/node_registry.json` | No |
| `verify_models.py` | Check model files vs. `configs/models/model_registry.json` | No |

## Runtime Platform (Epic 2)

| Script | Purpose | Installs? |
|--------|---------|-----------|
| `runtime_report.py` | Unified health report (human, `--summary`, `--json`) | No |
| `validate_assets.py` | Asset registry validation (`--workflow`, `--type`, `--json`) | No |

See [core/runtime/README.md](../runtime/README.md) and [docs/runtime-platform.md](../../docs/runtime-platform.md).

### Usage

```bash
# From repository root
python core/scripts/bootstrap_repo.py
python core/scripts/validate_environment.py
python core/scripts/validate_paths.py
python core/scripts/validate_manifests.py
python core/scripts/list_workflows.py
python core/scripts/runtime_report.py
python core/scripts/runtime_report.py --json
python core/scripts/check_nodes.py
python core/scripts/verify_models.py
python core/scripts/sync_outputs.py --dry-run
```

### Notebook integration

- **Cell 3b** — Repository bootstrap validation (after Drive mount)
- **Cell 3c** — Runtime platform health (`runtime_report.py`)

Post-install: `check_nodes.py`, `verify_models.py`. See [docs/colab-control-panel.md](../../docs/colab-control-panel.md).

## Planned Scripts (future)

| Script | Phase | Purpose |
|--------|-------|---------|
| `install_all.sh` | 1c | Orchestrate ComfyUI install + node install |
| `batch_runner.py` | 7 | Execute workflow chains over input datasets |

Colab-specific logic stays in `colab/utilities/`. Generic validation stays here.
