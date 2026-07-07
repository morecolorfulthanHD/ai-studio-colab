# Asset Registry

Unified cross-cutting asset inventory for AI Studio.

**Manifest:** `asset_registry.json`

The asset registry complements — but does not replace — `model_registry.json` and `workflow_registry.json`. See [docs/asset-registry.md](../../docs/asset-registry.md).

```bash
python core/scripts/validate_assets.py
python core/scripts/validate_assets.py --summary
python core/scripts/validate_assets.py --workflow base_txt2img
```
