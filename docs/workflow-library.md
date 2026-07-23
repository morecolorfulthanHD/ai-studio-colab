# Workflow Library (Package 4.8)

Three workflow layers:

1. **Canonical** — Git-managed source of truth under `workflows/**/workflow.json` with sibling `manifest.json`. Never mutated by preparation.
2. **Prepared** — Parameterized instance with `prep_<uuid>` under runtime `/content/ai-studio-runtime/workflows/prepared/`, Drive `AI_Studio/workflows/prepared/`, and optional project mirror. Not a generation.
3. **Executed snapshot** — Package 4.7 exact UI/API capture after ComfyUI runs. Remains authoritative for reproducibility.

## Statuses

| Workflow | Production | Notes |
|----------|------------|-------|
| `base/txt2img` | ready | Accepted quality |
| `base/img2img` | partial | Use with caution |
| `base/outpainting` | partial | Use with caution |
| `base/inpainting` | experimental | Requires `--allow-experimental` / notebook YES |
| `reference/qwen_image_edit` | benchmark_only | `--allow-benchmark`; no auto model download |
| `reference/flux_fill` | benchmark_only | Non-commercial/gated; no license automation |

## CLIs

```bash
python core/scripts/workflow_catalog.py --summary
python core/scripts/workflow_info.py --workflow base/txt2img --show-parameters --check-readiness
python core/scripts/check_workflow_readiness.py --workflow base/txt2img
python core/scripts/prepare_workflow.py --workflow base/txt2img --param positive_prompt="..." --param seed=123
python core/scripts/list_prepared_workflows.py
python core/scripts/prepared_workflow_info.py --preparation-id prep_<uuid>
python core/scripts/validate_prepared_workflow.py --preparation-id prep_<uuid>
python core/scripts/open_prepared_workflow.py --preparation-id prep_<uuid>
```

`open_prepared_workflow.py` copies JSON into ComfyUI `user/default/workflows/` for manual load. It does **not** auto-queue prompts or drive the browser.

## Loading prepared workflows

1. Prepare via notebook **10. Workflow Library** or CLI.
2. Run `open_prepared_workflow.py` (or notebook option 8).
3. In ComfyUI, open the Workflows sidebar / Load the `ai_studio_prep_*.json` file.
4. Inspect or edit, then Run.
5. Autosync + Package 4.7 snapshots capture the **executed** graph (including manual edits).
