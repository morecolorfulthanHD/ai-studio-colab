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

Catalog discovery shows **BENCHMARK ONLY** by default (use `--exclude-benchmark` to hide).

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

`open_prepared_workflow.py` writes a ComfyUI loading copy under `user/default/workflows/` **and** registers the same bytes via the ComfyUI `/api/userdata` API (frontend `storeUserData` / `getUserData` / `listUserDataFullInfo` shape) so the Workflows sidebar can open the graph. It does **not** auto-queue prompts or confirm the browser canvas loaded.

**Live Package 4.8.1 failure (documented accurately):** The prepared workflow appeared in the Workflows sidebar, but left-click did not load the graph, right-click Insert did not work, dragging did not work, and the canvas remained blank. Successful filesystem placement or userdata byte retrieval alone was **not** treated as proof of browser graph loading.

**Root cause (traced from Comfy-Org frontend / user_manager, not guessed):** Discovery uses `GET /api/userdata?dir=workflows&recurse=true&split=false&full_info=true`. Open uses `GET /api/userdata/{encodeURIComponent('workflows/<file>.json')}` → parse JSON → validate as a workflow object → frontend graph-loading path. Save/register uses `POST /api/userdata/{encodeURIComponent(...)}?overwrite=true&full_info=true` with the raw workflow JSON body. `/api` routes are preferred to match frontend behavior; bare `/userdata` remains a compatibility fallback. Contributing issues included collision sibling names (`_1`) leaving a stale sidebar entry, and sidebar Refresh after external registration (known frontend sync bug). Package 4.8.2 overwrites the deterministic `ai_studio_<prep_id>.json` name, posts with `full_info=true`, verifies listing size + schema + node/link counts, and instructs a hard browser tab reload + left-click (never sidebar Refresh / Insert / drag). Browser canvas rendering remains explicitly unverified programmatically.

## Loading prepared workflows

1. Prepare via notebook **10. Workflow Library** or CLI.
2. Run `open_prepared_workflow.py` (or notebook option 8) while ComfyUI is running when possible.
3. Open the ComfyUI page and **hard-reload the entire browser tab** after external registration (do **not** use the Workflows sidebar Refresh icon for this test).
4. Open the **Workflows** sidebar and **left-click** the exact deterministic `ai_studio_prep_*.json` filename.
5. Confirm a graph with nodes appears; review parameters; click **Run** manually when ready.
6. If left-click still fails, File → Load the filesystem loading copy path printed by the CLI remains a truthful fallback.
7. Automatic browser graph confirmation is unavailable — verify the canvas manually. Do not use right-click Insert, dragging, or expect automatic queueing.
8. Autosync + Package 4.7 snapshots capture the **executed** graph (including manual edits).

Use `diagnose_prepared_workflow_loading.py` for read-only server-side checks (source on disk, loading copy, userdata listing/GET). Use `reprepare_workflow.py` to allocate a **new** preparation from an existing archive without mutating the original.
