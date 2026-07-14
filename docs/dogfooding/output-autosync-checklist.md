# Dogfooding Checklist — Output Autosync (Package 4.4)

Zero-command acceptance: after Launch + ComfyUI Run, outputs appear on Drive with verified hashes and evidence — no manual `sync_outputs.py` / `verify_generation.py`.

## Operator flow

1. Launch AI Studio (full mode).
2. Confirm watcher starts automatically with ComfyUI (`Output autosync watcher started`).
3. Open ComfyUI and run one txt2img workflow.
4. Do **nothing else** (no sync cells/commands).
5. Confirm the file appears under `/content/drive/MyDrive/AI_Studio/outputs/`.
6. Confirm `/content/drive/MyDrive/AI_Studio/logs/generation_evidence.jsonl` contains a `verified` row with matching SHA-256.
7. Run a second image with the same SaveImage prefix.
8. Confirm collision-safe Drive copy and a second evidence row.
9. Restart the watcher (or relaunch ComfyUI).
10. Confirm no duplicate Drive copies for the same prompt/output/hash key.

## Status checks (optional)

```bash
python /content/ai-studio-colab/core/scripts/run_output_watcher.py --status
python /content/ai-studio-colab/core/scripts/runtime_report.py --summary
python /content/ai-studio-colab/core/scripts/dogfood_core_runtime.py
```

## Watcher concurrency

- Exclusive lock is acquired **before** constructing `OutputAutoSyncService` or cleaning temps.
- Duplicate starts are idempotent no-ops (no temp cleanup, no evidence/index mutation).
- `--status` is read-only; `--stop` clears only confirmed stale locks; `--once` uses the same exclusive lock.
## Recovery after Drive failures

Failed or pending evidence rows are **retryable**. Only verified outputs enter the permanent processed index.

On watcher restart / `--once` reconciliation:
1. Retry ledger rows that are pending/failed when the local ComfyUI file still exists and SHA-256 matches.
2. Append a new verified evidence row on success (append-only status transition).
3. If the local source is missing, keep the failed evidence and stop retrying that key (no infinite loop).
4. Never delete preexisting Drive outputs; only watcher temp files (`.ai_studio_autosync_tmp.*`) are cleaned.

## Pass / Fail

**PASS:** completion detected, stable file copied, size+SHA verified, evidence appended, duplicates suppressed; failed syncs recover after restart when the local source remains.

**FAIL:** filename-only “verification”, overwrite of Drive files, deletion of ComfyUI outputs, requiring manual sync commands, or treating failed evidence as permanent deduplication.

