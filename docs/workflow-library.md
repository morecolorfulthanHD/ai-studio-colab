# Workflow Library (Package 4.8 / 4.9 / 4.10)

Four workflow layers:

1. **Canonical workflow** — Git-managed source of truth under `workflows/**/workflow.json` with sibling `manifest.json`. Never mutated by preparation.
2. **Preparation** — Parameterized intent with `prep_<uuid>` under runtime `/content/ai-studio-runtime/workflows/prepared/`, Drive `AI_Studio/workflows/prepared/`, and optional project mirror. Records what the user intended before Run.
3. **Executed generation** — Package 4.7 `gen_<uuid>` snapshot after ComfyUI runs. Authoritative record of what actually executed (including the actual seed when `seed_mode=randomize`).
4. **Reproduction preparation** — Package 4.10: a **new** `prep_<uuid>` derived from a completed `gen_<uuid>`. Uses the executed generation state (not the original preparation intent) and defaults to `seed_mode=fixed`.

Never mutate a source generation snapshot or the original preparation when reproducing.

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
python core/scripts/prepare_workflow.py --workflow base/txt2img --param positive_prompt="..." --param seed=123 --param seed_mode=fixed
python core/scripts/list_prepared_workflows.py
python core/scripts/prepared_workflow_info.py --preparation-id prep_<uuid>
python core/scripts/validate_prepared_workflow.py --preparation-id prep_<uuid>
python core/scripts/open_prepared_workflow.py --preparation-id prep_<uuid>
python core/scripts/diagnose_prepared_workflow_loading.py --preparation-id prep_<uuid>
python core/scripts/reprepare_workflow.py --preparation-id prep_<uuid>
python core/scripts/prepare_from_generation.py --generation-id gen_<uuid>
python core/scripts/compare_generation_reproduction.py --source-generation gen_<uuid> --reproduction-preparation prep_<uuid>
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

**Package 4.8.3 live investigation finding (supersedes serialization hypothesis):**

| Path | Result |
|------|--------|
| SERVER/LOCALHOST registration + GET | PASS |
| Browser through Colab `prod.colab.dev` — native Save As POST `/api/userdata/workflows%2F…` | FAIL **405** Allow: GET,HEAD |
| Browser through Colab proxy — prepared workflow GET | FAIL **404** |

Root cause: frontend builds `encodeURIComponent('workflows/<file>.json')` → `workflows%2F…`. The Colab Google reverse proxy decodes `%2F` to `/` before aiohttp. Stock ComfyUI registers `/userdata/{file}` where `{file}` matches **one** path segment, so `/api/userdata/workflows/<file>.json` misses the userdata handler and falls through to `web.static('/', web_root)` (GET/HEAD only).

**Package 4.8.4 compatibility:** Reversible rewrite of installed `app/user_manager.py` routes to `{file:.*}` / `{dest:.*}` (same approach as upstream Comfy-Org/ComfyUI#12468), applied at install (`install.sh --execute`) and before notebook `launch_comfyui`. No workflow serialization change. No ComfyUI version pin. Restart ComfyUI after apply.

**Live Package 4.8.4 browser acceptance (partial):** Native ComfyUI persistence/open worked. Prepared workflow `prep_870c685b-751a-4ed8-ac2c-ad12c4bae42b` (`base/txt2img`, project `mountain-demo`) appeared in the sidebar, left-click opened the seven-node graph, and Run generated a local image. That live image did **not** appear in `AI_Studio/outputs/` or `AI_Studio/projects/mountain-demo/outputs/`.

**Package 4.8.5:** The live symptom (ComfyUI Save Image preview present; both Drive trees empty) is consistent with a dead watcher **or** an unresolved completed-history output. Live Colab was not available during implementation, so neither the exact history shape of `prep_870c685b-751a-4ed8-ac2c-ad12c4bae42b` nor watcher liveness during that run is proven.

Proven from code: flattened-only extraction could miss nested history shapes; a completed SaveImage prompt could become permanently resolved without a usable file; a single failed initial `/history` poll could exit the watcher and leave Full mode running. Package 4.8.5 keeps SaveImage prompts retryable, accepts nested `ui`/`output` images, uses **fail-closed** prefix recovery (never newest-alone, never unique-prefix-alone, never when competitor history lookup is unavailable), retries initial history access for a bounded window, and copies preparation linkage onto evidence + snapshots. No userdata-route change. No `/prompt`. Live Colab acceptance is required to identify which path caused the observed run.

**Package 4.8.3 investigation posture:** Capture live environment + browser console/network evidence with `diagnose_live_comfyui_workflow_open.py`. `open_prepared_workflow.py` reports dual status:

- `SERVER REGISTRATION: VERIFIED|PARTIAL|FAILED|UNVERIFIED`
- `BROWSER GRAPH OPEN: UNVERIFIED` (never auto-claimed)

**Live Package 4.8.1 failure (documented accurately):** The prepared workflow appeared in the Workflows sidebar, but left-click did not load the graph, right-click Insert did not work, dragging did not work, and the canvas remained blank. Successful filesystem placement or userdata byte retrieval alone was **not** treated as proof of browser graph loading.

**Root cause tracing (frontend/user_manager):** Discovery uses `GET /api/userdata?dir=workflows&recurse=true&split=false&full_info=true`. Open uses `GET /api/userdata/{encodeURIComponent('workflows/<file>.json')}` → parse JSON → frontend graph-loading path. Save/register uses `POST …?overwrite=true&full_info=true` with raw JSON. `/api` preferred; bare `/userdata` fallback. Package 4.8.2 deterministic overwrite + listing checks remain; Package 4.8.4 makes those browser requests reachable through the Colab proxy.

## Loading prepared workflows

1. Prepare via notebook **10. Workflow Library** or CLI.
2. Ensure Package 4.8.4 userdata route compat is applied (automatic on Launch / `install.sh --execute`, or run `apply_comfyui_userdata_route_compat.py --apply`) and **restart ComfyUI**.
3. Run `open_prepared_workflow.py` (or notebook option 8) while ComfyUI is running when possible.
4. Treat `SERVER REGISTRATION: VERIFIED` as server-side only; `BROWSER GRAPH OPEN` remains unverified until you confirm the canvas.
5. Open the ComfyUI page (Colab proxy URL) and **hard-reload the entire browser tab** after external registration (do **not** use the Workflows sidebar Refresh icon for this test).
6. Open the **Workflows** sidebar and **left-click** the exact deterministic `ai_studio_prep_*.json` filename.
7. Confirm a graph with nodes appears; review parameters; click **Run** manually when ready.
8. If left-click still fails, re-run `diagnose_live_comfyui_workflow_open.py --preparation-id <prep_id> --json` and check `userdata_route_compat.compatible` plus encoded/decoded path probes. File → Load remains a truthful fallback.
9. Automatic browser graph confirmation is unavailable — verify the canvas manually. Do not use right-click Insert, dragging, or expect automatic queueing.
10. Autosync + Package 4.7 snapshots capture the **executed** graph (including manual edits).

Use `diagnose_prepared_workflow_loading.py` for read-only server-side checks. Use `diagnose_live_comfyui_workflow_open.py` for environment/version capture, integrity, proxy-route probes, and DevTools collection steps. Use `reprepare_workflow.py` to allocate a **new** preparation from an existing archive without mutating the original.

## Package 4.9 — prepared execution controls

`base/txt2img` preparations expose an explicit **seed_mode**:

| seed_mode | KSampler `control_after_generate` | Repeated Run behavior |
|-----------|-----------------------------------|------------------------|
| `fixed` (default) | `fixed` | Same initial seed; identical image when other params are unchanged |
| `randomize` | `randomize` | ComfyUI advances the seed after each completed generation |

Existing callers that pass only `seed=<number>` keep the accepted 4.8.5 fixed/reproducible behavior. Invalid values such as `seed_mode=foo` fail with a clear error (no traceback).

**Three layers stay distinct:**

1. **Preparation archive** (`AI_Studio/workflows/prepared/<prep_id>/` and the project mirror) — original prepared intent, including the original seed and `seed_mode`. Immutable. Opening/running must not rewrite it.
2. **ComfyUI user copy** (`user/default/workflows/ai_studio_prep_<uuid>.json` / userdata) — runtime-editable working copy. After a randomized Run, ComfyUI may change the seed in this copy only.
3. **Generation snapshot** — actual execution. Records the seed ComfyUI used for that prompt, which may differ from the archived preparation seed when `seed_mode=randomize`.

Reopening a prepared workflow from AI Studio always reloads the archival preparation (original seed + original `seed_mode`). It does not persist the last randomized runtime seed back into the archive.

Legacy 4.8.x preparations that omit `seed_mode` inspect/open as `fixed` when `control_after_generate` is fixed or missing. No migration is required.

`save_prefix` remains the ComfyUI local Save Image prefix. Permanent Drive names stay `txt2img_<YYYYMMDD>_<six-digit-sequence>.png`.

## Package 4.10 — generation reproduction preparation

**Reproduce generation** means: create a **new fixed preparation** from the **executed generation snapshot**. It does **not** queue `/prompt`, auto-run, or browser-automate ComfyUI.

Critical seed distinction:

| Layer | Seed meaning |
|-------|----------------|
| Randomized preparation archive | Initial / intent seed (e.g. `246802468`) with `seed_mode=randomize` |
| Executed generation snapshot | Actual seed ComfyUI used (e.g. `603180018352167`) |
| Reproduction preparation | Uses the **execution** seed with `seed_mode=fixed` |

CLI:

```bash
python core/scripts/prepare_from_generation.py --generation-id gen_<uuid>
python core/scripts/prepare_from_generation.py --generation-id <bare-uuid> --project mountain-demo
python core/scripts/compare_generation_reproduction.py \
  --source-generation gen_<uuid> \
  --reproduction-preparation prep_<uuid>
```

Eligibility:

- `workflow_snapshot_status=complete` → allowed when required executed params recover
- `partial` → allowed only if all required execution parameters are recoverable without guessing
- `unavailable` / legacy missing snapshot → refuse with a clear error

Batch policy: selecting one `generation_id` from a multi-image batch prepares the **original batch execution** (`reproduction_scope=source_batch_execution`, original `batch_size`) because per-image latent identity is not preserved in generation snapshots. Isolated `batch_size=1` reduction is not claimed. When `batch_size` itself cannot be recovered, reproduction fails closed.

Save-prefix policy: reproduction preps use `ai_studio_repro_<short-gen-id>`. Permanent Drive naming is unchanged.

Open the resulting prep through the existing **Open prepared workflow** path (Package 4.8.4 userdata compatibility unchanged).
