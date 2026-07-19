# Dogfooding Checklist — Output Autosync (Package 4.5.2)

Zero-command acceptance: after Launch + ComfyUI Run, outputs appear on Drive with verified hashes and evidence — **no manual** `sync_outputs.py` / `verify_generation.py` in the normal operator flow.

## Critical: notebook menu may stay open

Leaving the control panel at `Select:` after Full mode launch is **correct** and must not stop autosync.

- The watcher runs as an independent subprocess (`start_new_session=True`).
- WebSocket, history reconciliation, Drive copy, and evidence updates continue without further notebook interaction.
- Do **not** exit the menu (option `0`) solely to “make sync work.”

## Runtime-aware ownership

Numeric PIDs are not watcher identities across Colab VM restarts. A valid watcher
must match the current ephemeral runtime ID, Linux boot ID, process start ticks,
repository watcher command line, and a fresh heartbeat.

Authoritative current-runtime state is ephemeral:

```text
/content/ai-studio-runtime/runtime_identity.json
/content/ai-studio-runtime/output-watcher/watcher.lock
/content/ai-studio-runtime/output-watcher/watcher.pid
/content/ai-studio-runtime/output-watcher/watcher_status.json
```

Persistent history remains on Drive:

```text
/content/drive/MyDrive/AI_Studio/logs/generation_evidence.jsonl
/content/drive/MyDrive/AI_Studio/logs/autosync/output_watcher_processed.json
/content/drive/MyDrive/AI_Studio/logs/autosync/output_watcher.log
```

Legacy Drive lock/PID/status files are historical only. They cannot suppress
startup or make a fresh runtime report `watcher: OK`.

## Fresh-runtime regression acceptance

1. Fresh runtime. Launch AI Studio (Full mode).
2. Confirm launch prints `OutputWatcher: OK`, not merely “started.”
3. Option 8 must show current `runtime_id`, `boot_id`, heartbeat,
   `ownership_state=current_runtime`, and `watcher=OK`.
4. Leave the notebook at `Select:` — do not enter `0`.
5. Create/activate project `mountain-demo`, then open ComfyUI in another tab.
6. Generate **txt2img image A**. Do nothing after Run.
7. Within the reconciliation interval, confirm both:
   - `AI_Studio/outputs/txt2img_YYYYMMDD_000001.png` (UTC date)
   - `AI_Studio/projects/mountain-demo/outputs/txt2img_YYYYMMDD_000001.png`
8. Confirm `generation_evidence.jsonl` has pending then verified rows with
   `source_filename`, `drive_filename`, and matching local/Drive SHA-256.
9. Generate image B with the same SaveImage prefix. Confirm sequence `000002`;
   image A remains unchanged.
10. Restart the entire Colab runtime and launch Full mode again.
11. Confirm no July-16-style persistent lock/PID/status suppresses the new watcher.
12. Generate image C and confirm automatic global/project persistence without
    any manual recovery command.

**Do not run `--once` during acceptance.** It masks background watcher startup
defects. Also do not run `sync_outputs.py`, `verify_generation.py`, or manual
copy commands.

## Permanent Drive naming

- Format: `<capability>_<YYYYMMDD>_<sequence>.<ext>` (e.g. `txt2img_20260715_000001.png`).
- Sequence is capability-specific, zero-padded, resets each UTC day, survives watcher restart.
- Never reuse the ComfyUI filename; never overwrite; never append `.1` / `.2`.
- Original ComfyUI name is stored in evidence as `source_filename`.

## Status checks (optional)

```bash
python /content/ai-studio-colab/core/scripts/run_output_watcher.py --status
python /content/ai-studio-colab/core/scripts/run_output_watcher.py --diagnose
python /content/ai-studio-colab/core/scripts/runtime_report.py --summary
python /content/ai-studio-colab/core/scripts/dogfood_core_runtime.py
```

`--diagnose` is read-only. It inspects runtime/lock/process identity, heartbeat,
ComfyUI/history/local outputs, latest evidence, Drive, and active project without
syncing, clearing locks, or starting/stopping a watcher.

`runtime_report` distinguishes current healthy ownership from `old_runtime`,
`pid_reused`, `foreign_process`, `dead`, `stale_heartbeat`, `malformed`, and
`absent`. A stale or historical heartbeat never reports `watcher: OK`.

## Watcher concurrency

- Exclusive lock is acquired **before** constructing `OutputAutoSyncService` or cleaning temps.
- Duplicate starts are idempotent no-ops (no temp cleanup, no evidence/index mutation).
- `--status` and `--diagnose` are read-only.
- Startup self-heals stale, foreign, old-runtime, PID-reused, malformed, or
  heartbeat-stale ownership while preserving evidence, processed history,
  outputs, project outputs, and logs.
- A newly started watcher reconciles completed history immediately, before
  claiming `OutputWatcher: OK`.

## Detection reliability

- WebSocket is primary; periodic history reconciliation is the safety net.
- Prompt IDs are marked seen only after a resolved sync attempt.
- Missed websocket events, disconnects, or watcher-before-ComfyUI startup must still recover via history poll / reconcile.

## Recovery after Drive failures

Failed or pending evidence rows are **retryable**. Only verified outputs enter the permanent processed index.

On watcher startup / periodic reconciliation:
1. Retry ledger rows that are pending/failed when the local ComfyUI file still exists and SHA-256 matches.
2. Append a new verified evidence row on success (append-only status transition).
3. If the local source is missing, keep the failed evidence and stop retrying that key (no infinite loop).
4. Never delete preexisting Drive outputs; only watcher temp files (`.ai_studio_autosync_tmp.*`) are cleaned.
5. Generations still in ComfyUI history/output are recovered automatically (pending → verified → unique Drive name).

## Pass / Fail

**PASS:** completion detected with notebook at `Select:`; permanent Drive names; size+SHA verified; evidence pending→verified; same SaveImage prefix yields distinct assets; duplicates suppressed by execution identity + content hash.

**FAIL:** requiring menu exit for sync; filename-only verification; overwrite of Drive files; reusing ComfyUI filenames on Drive; deletion of ComfyUI outputs; requiring manual sync; treating failed evidence as permanent deduplication; marking history seen before successful sync.
