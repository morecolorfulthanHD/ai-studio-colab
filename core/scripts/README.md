# Core Scripts

Cross-engine utility scripts for bootstrap, validation, and batch processing.

**All scripts use standard library Python only.** Safe to run in Colab without additional dependencies.

## Bootstrap & Validation (Phase 1)

| Script | Purpose | Notebook-callable |
|--------|---------|-------------------|
| `bootstrap_repo.py` | Validate repo structure; document git sync hook | Yes |
| `validate_environment.py` | Python, Colab, Drive, GPU checks | Yes |
| `validate_paths.py` | Validate Colab/Drive/repo paths from manifest | Yes |
| `validate_manifests.py` | Validate JSON manifests under `configs/` | Yes |
| `list_workflows.py` | List workflow JSON files by category | Yes |
| `sync_outputs.py` | Copy latest ComfyUI output to Drive (`--dry-run` supported) | Yes |

### Usage

```bash
# From repository root
python core/scripts/bootstrap_repo.py
python core/scripts/validate_environment.py
python core/scripts/validate_paths.py
python core/scripts/validate_manifests.py
python core/scripts/list_workflows.py
python core/scripts/sync_outputs.py --dry-run
```

## Planned Scripts (future phases)

| Script | Phase | Purpose |
|--------|-------|---------|
| `check_nodes.py` | 1b | Compare installed nodes vs. `configs/nodes/node_registry.json` |
| `verify_models.py` | 1b | Check models against `configs/models/model_registry.json` |
| `install_all.sh` | 1b | Orchestrate full platform install |
| `batch_runner.py` | 7 | Execute workflow chains over input datasets |

Colab-specific logic stays in `colab/utilities/`. Generic validation stays here.
