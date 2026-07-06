# Configuration Layer

Centralized, version-controlled settings referenced by workflows and install scripts.

| Directory | Purpose |
|-----------|---------|
| [models/](models/) | `model_registry.json` — model categories, paths, requirements |
| [nodes/](nodes/) | `node_registry.json` — custom node repos and install metadata |
| [paths/](paths/) | `colab_paths.json` — Colab runtime and Drive path mappings |
| [presets/](presets/) | `default_generation_presets.json` — generation parameter sets |
| [workflows/](workflows/) | `workflow_registry.json` — workflow index and dependencies |

Workflows reference config keys, never hardcoded filenames or absolute paths.

Validate all manifests:

```bash
python core/scripts/validate_manifests.py
```
