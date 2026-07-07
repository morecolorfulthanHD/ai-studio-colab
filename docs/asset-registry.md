# Asset Registry

The unified asset inventory layer for AI Studio Colab.

## Why It Exists

Before installer execution, the platform needs one abstraction that answers cross-cutting questions:

- What assets exist?
- What assets are required?
- What assets are missing?
- Where should each asset live?
- Which workflows require which assets?
- Which assets are reusable across engines?
- Which assets are use-case-specific?

`model_registry.json` focuses on **model weights**. `workflow_registry.json` focuses on **workflow definitions**. `asset_registry.json` is the **broader inventory** spanning models, workflows, prompts, references, anchors, and extracted maps.

## Manifest Location

```
configs/assets/asset_registry.json
```

## Entry Schema

| Field | Description |
|-------|-------------|
| `id` | Unique asset identifier |
| `name` | Human-readable name |
| `asset_type` | checkpoint, controlnet, lora, vae, embedding, upscaler, ipadapter, clip, insightface, svd, animatediff_motion, workflow, prompt_library, reference_image, character_anchor, environment_anchor, extracted_map |
| `category` | Grouping within type (e.g. diffusion, structural, identity) |
| `scope` | core, shared, workflow, use_case, experimental |
| `engine` | comfyui, a1111, shared, future |
| `intended_path` | Repo-relative canonical path |
| `runtime_path` | Colab/Drive runtime path (optional) |
| `required_for` | Workflow IDs that require this asset |
| `status` | planned, active, missing, installed, external |
| `source_type` | huggingface, repository, external, generated |
| `source_url` | Download or reference URL |
| `license_notes` | License summary |
| `notes` | Free-form documentation |

## How Registries Relate

```
workflow_registry.json
    │  required_models, required_nodes
    ▼
model_registry.json          node_registry.json
    │                              │
    └──────────┬───────────────────┘
               ▼
        asset_registry.json  ◄── cross-cutting inventory
               │
               ▼
        AssetManager / validate_assets.py
```

| Registry | Focus | Removed? |
|----------|-------|----------|
| `model_registry.json` | Model filenames, runtime paths, model-family metadata | No — kept for model-specific tooling |
| `node_registry.json` | Custom node repos and install metadata | No |
| `workflow_registry.json` | Workflow JSON paths and dependencies | No |
| `asset_registry.json` | All asset types including non-model assets | New unified layer |

### Future consolidation (not performed now)

- Model entries could be generated from `asset_registry` filtered by `asset_type`
- Workflow assets could sync `required_for` ↔ `workflow_registry.required_models`
- A single manifest with typed views is possible but deferred to avoid breaking Epic 1 tooling

## Scopes and Engines

| Scope | Meaning |
|-------|---------|
| `core` | Platform assets required by base workflows |
| `shared` | Reusable across projects and engines |
| `workflow` | Tied to a specific workflow or pipeline |
| `use_case` | Project-specific (validation datasets only) |
| `experimental` | Provisional or test assets |

| Engine | Meaning |
|--------|---------|
| `comfyui` | ComfyUI-specific path or node dependency |
| `a1111` | Automatic1111-specific |
| `shared` | Both engines or engine-agnostic |
| `future` | Reserved for upcoming inference servers |

## Workflow Dependencies

Query assets for a workflow:

```bash
python core/scripts/validate_assets.py --workflow base_txt2img
```

```python
from core.runtime.asset_manager import AssetManager

manager = AssetManager()
assets = manager.assets_for_workflow("base_txt2img")
missing = manager.missing_required("base_txt2img")
```

Workflow registry `required_models` should align with asset `id` values over time. Full auto-sync is deferred.

## Use Cases (Not Core Architecture)

Use-case assets use `scope: use_case` and live under `use_cases/<project>/`:

| Asset type | Example use |
|------------|-------------|
| `character_anchor` | Facial identity reference for a virtual character |
| `environment_anchor` | Scene reference set for environment consistency |
| `reference_image` | General reference photos |
| `prompt_library` | Project-specific prompt templates |

A future validation project (e.g. Zara Morrison) would add entries pointing to `use_cases/zara_morrison/` paths. The platform core never embeds project-specific logic.

## Tools

| Tool | Purpose |
|------|---------|
| `core/runtime/asset_manager.py` | Load, group, query assets |
| `core/scripts/validate_assets.py` | CLI validation (`--json`, `--summary`, `--type`, `--workflow`) |
| `runtime_report.py` | Includes asset summary in health report |
| `runtime_health.py` | `assets` health component |

## Status Values

| Status | Meaning |
|--------|---------|
| `planned` | Registered but not required yet |
| `active` | Required for production workflows |
| `missing` | Known absent; should be acquired |
| `installed` | Present on disk (detected or declared) |
| `external` | Lives outside repo/Drive standard paths |

Detection uses `intended_path` (repo) and `runtime_path` (Drive) when available. No downloads are performed by validation tools.
