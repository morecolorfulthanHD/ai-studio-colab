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

**Live Package 4.8.2 failure (operational acceptance NOT met):** Preparation `prep_870c685b-751a-4ed8-ac2c-ad12c4bae42b` had deterministic filename in the sidebar, ComfyUI reachable, userdata registered/verified/listed, list size match, schema valid, 7 nodes / 9 links, archival unchanged — yet after a full hard reload, left-clicking the exact workflow name did nothing and the canvas stayed blank. Server-side success alone is **not** browser graph loading.

**Package 4.8.3 investigation posture:** Do not invent another speculative registration/serialization fix. Capture live environment + browser console/network evidence with `diagnose_live_comfyui_workflow_open.py`, compare against a known-good workflow saved by the *same* frontend (`ai_studio_known_good_control.json`), run integrity validation, and only then apply a narrow fix justified by that evidence. `open_prepared_workflow.py` now reports dual status:

- `SERVER REGISTRATION: VERIFIED|PARTIAL|FAILED|UNVERIFIED`
- `BROWSER GRAPH OPEN: UNVERIFIED` (never auto-claimed)

**Live Package 4.8.1 failure (documented accurately):** The prepared workflow appeared in the Workflows sidebar, but left-click did not load the graph, right-click Insert did not work, dragging did not work, and the canvas remained blank. Successful filesystem placement or userdata byte retrieval alone was **not** treated as proof of browser graph loading.

**Root cause tracing (frontend/user_manager, not guessed):** Discovery uses `GET /api/userdata?dir=workflows&recurse=true&split=false&full_info=true`. Open uses `GET /api/userdata/{encodeURIComponent('workflows/<file>.json')}` → parse JSON → validate as a workflow object → frontend graph-loading path. Save/register uses `POST /api/userdata/{encodeURIComponent(...)}?overwrite=true&full_info=true` with the raw workflow JSON body. `/api` routes are preferred to match frontend behavior; bare `/userdata` remains a compatibility fallback. Contributing Package 4.8.1 issues included collision sibling names (`_1`) leaving a stale sidebar entry, and sidebar Refresh after external registration (known frontend sync bug). Package 4.8.2 overwrites the deterministic `ai_studio_<prep_id>.json` name and verifies listing/schema/counts, but live left-click still failed — hence 4.8.3 diagnostics before any further load-path change.

## Loading prepared workflows

1. Prepare via notebook **10. Workflow Library** or CLI.
2. Run `open_prepared_workflow.py` (or notebook option 8) while ComfyUI is running when possible.
3. Treat `SERVER REGISTRATION: VERIFIED` as server-side only; `BROWSER GRAPH OPEN` remains unverified until you confirm the canvas.
4. Open the ComfyUI page and **hard-reload the entire browser tab** after external registration (do **not** use the Workflows sidebar Refresh icon for this test).
5. Open the **Workflows** sidebar and **left-click** the exact deterministic `ai_studio_prep_*.json` filename.
6. Confirm a graph with nodes appears; review parameters; click **Run** manually when ready.
7. If left-click still fails, capture evidence with `diagnose_live_comfyui_workflow_open.py --preparation-id <prep_id> --json`, then run the known-good control Save As test. File → Load remains a truthful fallback.
8. Automatic browser graph confirmation is unavailable — verify the canvas manually. Do not use right-click Insert, dragging, or expect automatic queueing.
9. Autosync + Package 4.7 snapshots capture the **executed** graph (including manual edits).

Use `diagnose_prepared_workflow_loading.py` for read-only server-side checks. Use `diagnose_live_comfyui_workflow_open.py` for environment/version capture, integrity, known-good comparison, and exact DevTools collection steps. Use `reprepare_workflow.py` to allocate a **new** preparation from an existing archive without mutating the original.
