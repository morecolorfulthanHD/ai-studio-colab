# Dogfooding Checklist — Output Autosync (Package 4.5.1)

Zero-command acceptance: after Launch + ComfyUI Run, outputs appear on Drive with verified hashes and evidence — **no manual** `sync_outputs.py` / `verify_generation.py` in the normal operator flow.

## Critical: notebook menu may stay open

Leaving the control panel at `Select:` after Full mode launch is **correct** and must not stop autosync.

- The watcher runs as an independent subprocess (`start_new_session=True`).
- WebSocket, history reconciliation, Drive copy, and evidence updates continue without further notebook interaction.
- Do **not** exit the menu (option `0`) solely to “make sync work.”

## Operator flow (acceptance)

1. Fresh runtime. Launch AI Studio (Full mode).
2. Confirm watcher start message (`Output autosync watcher started`).
3. Leave the notebook at `Select:` — do nothing else in the notebook.
4. Open ComfyUI in another tab.
5. Generate **txt2img image A**. Do nothing.
6. Confirm Drive receives `txt2img_YYYYMMDD_000001.png` (permanent name, not the ComfyUI SaveImage name).
7. Confirm `generation_evidence.jsonl` has a `verified` row with `source_filename`, `drive_filename`, matching SHA-256.
8. Generate **txt2img image B** with the **same SaveImage prefix**. Do nothing.
9. Confirm Drive receives `txt2img_YYYYMMDD_000002.png`.
10. Confirm image A remains untouched on Drive.
11. Confirm evidence has **two** verified rows.
12. Repeat for img2img (`img2img_YYYYMMDD_000001.png`) and inpainting (`inpainting_YYYYMMDD_000001.png`).

## Permanent Drive naming

- Format: `<capability>_<YYYYMMDD>_<sequence>.<ext>` (e.g. `txt2img_20260715_000001.png`).
- Sequence is capability-specific, zero-padded, resets each UTC day, survives watcher restart.
- Never reuse the ComfyUI filename; never overwrite; never append `.1` / `.2`.
- Original ComfyUI name is stored in evidence as `source_filename`.

## Status checks (optional)

```bash
python /content/ai-studio-colab/core/scripts/run_output_watcher.py --status
python /content/ai-studio-colab/core/scripts/runtime_report.py --summary
python /content/ai-studio-colab/core/scripts/dogfood_core_runtime.py
```

`runtime_report` must distinguish **Watcher started** from **Watcher currently alive** (`liveness=alive` vs `started-but-dead` / `alive-stale-heartbeat`).

## Watcher concurrency

- Exclusive lock is acquired **before** constructing `OutputAutoSyncService` or cleaning temps.
- Duplicate starts are idempotent no-ops (no temp cleanup, no evidence/index mutation).
- `--status` is read-only; `--stop` clears only confirmed stale locks; `--once` uses the same exclusive lock.

## Detection reliability

- WebSocket is primary; periodic history reconciliation is the safety net.
- Prompt IDs are marked seen only after a resolved sync attempt.
- Missed websocket events, disconnects, or watcher-before-ComfyUI startup must still recover via history poll / reconcile.

## Recovery after Drive failures

Failed or pending evidence rows are **retryable**. Only verified outputs enter the permanent processed index.

On watcher restart / `--once` reconciliation:
1. Retry ledger rows that are pending/failed when the local ComfyUI file still exists and SHA-256 matches.
2. Append a new verified evidence row on success (append-only status transition).
3. If the local source is missing, keep the failed evidence and stop retrying that key (no infinite loop).
4. Never delete preexisting Drive outputs; only watcher temp files (`.ai_studio_autosync_tmp.*`) are cleaned.
5. Generations still in ComfyUI history/output are recovered automatically (pending → verified → unique Drive name).

## Pass / Fail

**PASS:** completion detected with notebook at `Select:`; permanent Drive names; size+SHA verified; evidence pending→verified; same SaveImage prefix yields distinct assets; duplicates suppressed by execution identity + content hash.

**FAIL:** requiring menu exit for sync; filename-only verification; overwrite of Drive files; reusing ComfyUI filenames on Drive; deletion of ComfyUI outputs; requiring manual sync; treating failed evidence as permanent deduplication; marking history seen before successful sync.
