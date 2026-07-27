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
python core/scripts/diagnose_prepared_workflow_loading.py --preparation-id prep_<uuid>
python core/scripts/reprepare_workflow.py --preparation-id prep_<uuid>
```

### Project resolution (Package 4.8.1)

`prepare_workflow.py` resolves project context automatically:

- `--global` — global archive only (no project mirror)
- `--project <slug-or-id>` — explicit project (errors if missing or archived)
- neither — uses the active project when set; otherwise global-only

The notebook Workflow Library menu does not pass `--project`; it relies on the active project pointer from **Workspace / Projects**.

Prepared artifacts land in:

- **Global archive:** `AI_Studio/workflows/prepared/<prep_id>/`
- **Project mirror** (when a project is active or selected): `AI_Studio/projects/<slug>/workflows/prepared/<prep_id>/`

`open_prepared_workflow.py` writes a ComfyUI loading copy under `user/default/workflows/` **and** registers the same bytes via the ComfyUI `/userdata` API so the Workflows sidebar can open the graph. It does **not** auto-queue prompts or confirm the browser canvas loaded.

**Root cause (Package 4.8 live Colab):** filesystem placement alone could list a workflow in the sidebar without registering it through userdata routes (`GET/POST /userdata`, `GET /v2/userdata`). Appearing in the sidebar was not treated as proof the graph could load. Package 4.8.1 POSTs the loading bytes, GETs them back, and verifies SHA-256 before instructing a manual left-click open.

## Loading prepared workflows

1. Prepare via notebook **10. Workflow Library** or CLI.
2. Run `open_prepared_workflow.py` (or notebook option 8) while ComfyUI is running when possible.
3. In ComfyUI, open the **Workflows** sidebar and **left-click** the `ai_studio_prep_*.json` workflow name.
4. If the sidebar does not list it, use **File → Load** on the filesystem loading copy path printed by the CLI.
5. Automatic browser graph confirmation is unavailable — verify the canvas manually.
6. Inspect or edit, then Run.
7. Autosync + Package 4.7 snapshots capture the **executed** graph (including manual edits).

Use `diagnose_prepared_workflow_loading.py` for read-only server-side checks (source on disk, loading copy, userdata listing/GET). Use `reprepare_workflow.py` to allocate a **new** preparation from an existing archive without mutating the original.
