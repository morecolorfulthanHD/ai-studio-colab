# Configuration Layer

Centralized, version-controlled settings referenced by workflows and install scripts.

| Directory | Purpose |
|-----------|---------|
| [models/](models/) | `model_registry.json` — model categories, paths, requirements |
| [nodes/](nodes/) | `node_registry.json` — custom node repos and install metadata |
| [paths/](paths/) | `colab_paths.json` — Colab runtime and Drive path mappings |
| [presets/](presets/) | `default_generation_presets.json` — generation parameter sets |
| [workflows/](workflows/) | `workflow_registry.json` — workflow index and dependencies |
| [assets/](assets/) | `asset_registry.json` — unified cross-cutting asset inventory |

Workflows reference config keys, never hardcoded filenames or absolute paths.

Registry relationships: [asset-registry.md](../docs/asset-registry.md).

Validate all manifests and assets:

```bash
python core/scripts/validate_manifests.py
python core/scripts/validate_assets.py --summary
```
