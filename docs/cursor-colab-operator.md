# Cursor Colab Operator Runbook

Orchestration only. Does **not** change Package 4.12.3 benchmark semantics.
Does **not** start Package 4.13. Does **not** re-run rejected FaceID/ReActor tests.

Config source of truth: [`configs/operator/colab_operator.json`](../configs/operator/colab_operator.json)

State machine: [`core/runtime/colab_operator.py`](../core/runtime/colab_operator.py)

---

## Canonical notebook

Open **only** the GitHub-backed control panel (never a Drive copy as source of truth):

**https://colab.research.google.com/github/morecolorfulthanHD/ai-studio-colab/blob/main/colab/notebooks/AI_Studio_Control_Panel_Colab.ipynb**

Identity markers to verify after open:

- “AI Studio Control Panel”
- “Repository Sync”
- `control_panel()` cell / menu

Reject stale Drive notebook duplicates.

---

## Operator state machine

| State | Meaning |
|-------|---------|
| `NOT_OPEN` | Browser not on canonical notebook |
| `COLAB_OPEN` | Notebook open; runtime unknown |
| `AUTH_REQUIRED` | **STOP** — user must complete auth/consent |
| `DISCONNECTED` | Runtime disconnected; Connect allowed |
| `CONNECTED` | Runtime connected |
| `REPO_SYNCED` | Repo clone/pull OK; HEAD should track `origin/main` |
| `AI_STUDIO_READY` | Run all done; control panel callable |
| `FULL_LAUNCH_RUNNING` | Launch full in progress |
| `FULL_LAUNCH_READY` | ComfyUI up; watcher healthy enough to proceed |
| `LIVE_QA_RUNNING` | Requested live QA/benchmark running |
| `HUMAN_REVIEW_REQUIRED` | **STOP** — human gate |
| `FAILED` | **STOP** — hard failure |
| `COMPLETE` | Requested workflow finished |

Reason from **visible labels/text**, not fixed pixel coordinates.

---

## Normal browser sequence

### A. OPEN

1. Navigate to canonical Colab URL from config.
2. Confirm notebook identity markers.
3. State → `COLAB_OPEN`.

### B. CONNECT

1. If UI shows Connect / Disconnected → click **Connect**.
2. State remains `DISCONNECTED` until connected evidence appears.
3. Wait until Connected (RAM/Disk / “Connected” indicators).
4. Only then: state → `CONNECTED`.

**Do not** treat Connect-click as connected.

### C. ENVIRONMENT

1. Prefer GPU runtime.
2. If wrong runtime type: **STOP and ask user** before changing billing/GPU (`may_change_gpu_runtime_without_asking=false`).

### D. REPO SYNC

1. Run Repository Sync / bootstrap cells.
2. Verify clone at `/content/ai-studio-colab` and branch `main` tracks `origin/main`.
3. State → `REPO_SYNCED`.

### E. RUN NOTEBOOK

1. **Runtime → Run all** (or required startup cells).
2. Wait until `control_panel()` menu is available (`=== AI Studio Control Panel ===`).
3. State → `AI_STUDIO_READY`.

### F. FULL LAUNCH

1. In control panel: select **`1`** — Launch (Safe / Minimal / Full).
2. Select mode **`full`**.
3. Wait for completion.
4. Warnings without hard fail → proceed (`FULL_LAUNCH_READY`).
5. Hard fail → `FAILED` and stop.
6. Verify ComfyUI URL printed and OutputWatcher not in FAIL/unhealthy state.

### G. LIVE QA (nested menus)

**Semantic rule:** after every selection, verify the next menu title before continuing.
If the expected title is missing → **STOP / reassess** (never blindly type the next number).

Path:

1. Main control panel → select **`9`** (Workspace / Projects)  
   → verify `=== Workspace / Projects ===`
2. Workspace / Projects → select **`13`** (Characters …)  
   → verify `=== Characters (Package 4.12 / 4.12.3) ===`
3. Characters → requested action:

| Need | Select | Notes |
|------|--------|-------|
| **Run production identity benchmark** | `11` | **Normal path** — one-action S1–S4 (prepare→execute→capture→QA→report) |
| Status / architecture report | `12` | Report only; capture ≠ production PASS |
| Advanced identity benchmark tools | `13` | Prepare / raw execute / diagnostics (debug escape hatch) |
| Package 4.12.3 consolidated QA | run `python core/scripts/qa_package4123.py` in repo | Offline/sim QA |
| Rejected FaceID/ReActor | **Do not re-run for production** | Status remains rejected |

Live execute sequence is **`9` → `13` → `11`**, not top-level `13` → `11`.

Helper: `navigation_sequence("run_production_identity_benchmark")` in `core/runtime/colab_operator.py`.

**GPU confirmation:** Interactive menu asks `[y/N]` before GPU work. If the originating user request **explicitly** asked Cursor to RUN the live production identity benchmark, Cursor may satisfy that routine confirmation automatically (`--operator-live-intent`). Merely opening Characters never authorizes GPU execution. Still stop for Google/Drive auth, billing, CAPTCHA, or other real consent gates.

Orchestrator: `core/scripts/run_production_identity_benchmark.py` — emits `status=COMPLETE|HUMAN_REVIEW_REQUIRED|FAILED` plus structured JSON fields (character, scenarios, prompt IDs, durable paths, report paths, consolidated QA).

**Preflight (before GPU scenarios):** ComfyUI reachable → InstantID live `/object_info` nodes → structural InstantID readiness → asset hash gates → license gate evaluation → OutputWatcher current-runtime health. Fail closed with actionable messages; never Full Reset.

**After scenario capture:** invokes authoritative Package 4.12.3 consolidated QA (`core.runtime.package4123_qa.run_consolidated_package4123_qa`). Consolidated QA failure forces `FAILED` (never `COMPLETE`).

Do not ask the user to paste routine Colab logs; collect visible cell output and Drive report paths yourself.

Character selection: explicit ID, else sole valid character auto-selected, else numbered pick — do not hard-code a character.
### H. OBSERVE

Collect without asking the user to paste logs when browser-visible:

- control panel / cell stdout
- ComfyUI status if needed
- Drive QA reports under `AI_Studio/logs/qa/`
- architecture ledger / output paths

Avoid unnecessary screenshots unless human visual review needs them.

### I. REPORT

Summarize:

- runtime state
- repo SHA (`git rev-parse HEAD` in clone)
- Full Launch result
- QA result / provisional vs fail
- whether human action is required

---

## Restart / reconnect policy

**Cursor may automatically:**

- reconnect a disconnected runtime
- rerun startup / Repository Sync cells
- rerun Full Launch after a recoverable runtime death when the runbook path applies

**Cursor must NOT automatically:**

- Full Reset
- Drive / model / project / history / benchmark-evidence deletion
- GPU/billing runtime changes without asking
- start Package 4.13
- re-run FaceID/ReActor for production validation
- weaken license or asset verification gates

If uncertain → ask the user.

---

## Auth / consent stop conditions

**STOP and ask the user** for:

- Google login
- ambiguous account chooser
- 2FA / passkey
- Drive mount consent
- Colab paid GPU / billing consent
- CAPTCHA
- browser security confirmation
- `HUMAN_REVIEW_REQUIRED` from automated QA
- Full Launch hard failure

After the user resolves the blocker → resume from last known state (`AUTH_RESOLVED` → continue sequence).

---

## Recommended Cursor Agent settings (document only)

Do **not** programmatically change user settings. Recommend:

- browser tooling enabled
- auto-run allowed for trusted routine Colab clicks (Connect, Run all, menu selects)
- destructive actions still require approval
- auth/consent always user-controlled

---

## Operator cancellation / lifecycle

Machine-local only (`%LOCALAPPDATA%\AI_Studio\operator\` on Windows).

```bash
python core/scripts/colab_operator_control.py begin --checkpoint "LABEL"
python core/scripts/colab_operator_control.py status
python core/scripts/colab_operator_control.py stop
python core/scripts/colab_operator_control.py stop --close-browser
python core/scripts/colab_operator_control.py clear-stale
python core/scripts/simulate_colab_operator_lifecycle.py
python core/scripts/simulate_operator_job_containment.py
```

**User stop/pause phrases** (`stop`, `pause`, `stop running`, …) ⇒ immediately
`stop`, verify CANCELLED/idle, do **not** auto-resume or relaunch Chrome.

Default `stop` prevents Chrome relaunch and kills owned helper processes; it does
**not** close an already-open dedicated Chrome window unless `--close-browser`.
Never kill normal/default-profile Chrome. Never disconnect Colab / Full Reset /
delete Drive / kill remote ComfyUI or OutputWatcher as part of local cancellation.

All operator-owned local children must launch via
`OperatorLifecycle.spawn_owned_helper` / `spawn_operator_process` (central API).
Transient helpers use Windows Job Object `KILL_ON_JOB_CLOSE` when `contain=True`.
Dedicated Chrome uses `kind=chrome` with containment forced off so parent death /
normal `stop` does not tear down an already-open operator browser.

Dedicated Chrome launch must go through
`python core/scripts/launch_operator_chrome.py --run-id <id>` (gated
`launch_chrome_for_run`).

**Cursor UI Stop limitation:** if Cursor kills the agent abruptly, Python `atexit`
hooks may not run. Mitigation: cooperative cancellation + PID registry + Windows
Job Object `KILL_ON_JOB_CLOSE` for contained helpers; helpers self-exit when
their `run_id` is cancelled or superseded.

---

## Safe notebook cell entry (CDP)

When driving Colab via Chrome CDP, **never** send text to the current caret
(`Input.insertText` alone). That append path produced:

```text
control_panel()control_panel()
SyntaxError: invalid syntax
```

Mandatory primitive: `core.runtime.colab_cdp_cells`

1. Prefer **run existing** when `getText()` already matches (`RUN_EXISTING`).
2. If source must change: **`cell.setText(desired)`** then verify with `getText()` —
   never caret-append.
3. Execute via the cell’s **`<colab-run-button>`** (shadow click) — do not retype
   source as part of Run.
4. Retries must be idempotent (no duplicated command glue).

Simulation: `python core/scripts/simulate_colab_cdp_cells.py`

---

## Local helpers

```bash
python core/scripts/report_colab_operator_state.py
python core/scripts/report_colab_operator_state.py --state DISCONNECTED
python core/scripts/simulate_colab_operator.py
python core/scripts/simulate_colab_cdp_cells.py
python core/scripts/simulate_colab_operator_lifecycle.py
python core/scripts/simulate_operator_job_containment.py
python core/scripts/colab_operator_control.py status
```

These do not open Colab (except the gated Chrome launcher when explicitly used).
