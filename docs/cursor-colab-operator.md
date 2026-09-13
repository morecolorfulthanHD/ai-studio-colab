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
2. Wait until Connected (RAM/Disk indicators).
3. State → `CONNECTED` (or `DISCONNECTED` → Connect).

### C. ENVIRONMENT

1. Prefer GPU runtime.
2. If wrong runtime type: **STOP and ask user** before changing billing/GPU (`may_change_gpu_runtime_without_asking=false`).

### D. REPO SYNC

1. Run Repository Sync / bootstrap cells.
2. Verify clone at `/content/ai-studio-colab` and branch `main` tracks `origin/main`.
3. State → `REPO_SYNCED`.

### E. RUN NOTEBOOK

1. **Runtime → Run all** (or required startup cells).
2. Wait until `control_panel()` menu is available.
3. State → `AI_STUDIO_READY`.

### F. FULL LAUNCH

1. In control panel: select **`1`** — Launch (Safe / Minimal / Full).
2. Select mode **`full`**.
3. Wait for completion.
4. Warnings without hard fail → proceed (`FULL_LAUNCH_READY`).
5. Hard fail → `FAILED` and stop.
6. Verify ComfyUI URL printed and OutputWatcher not in FAIL/unhealthy state.

### G. LIVE QA

Navigate: control panel → **`13` Characters**.

| Need | Select | Notes |
|------|--------|-------|
| Prepare InstantID architecture | `11` | Prepare only; not a quality claim |
| Run InstantID live execute + QA | `12` | Requires explicit user request + ack flags; GPU cost |
| Architecture / production identity report | `13` | Report only |
| Package 4.12.3 consolidated QA | run `python core/scripts/qa_package4123.py` in repo | Offline/sim QA |
| Rejected FaceID/ReActor | **Do not re-run for production** | Status remains rejected |

Default character when needed: `char_7471a702-55cf-4c7b-adb2-e17404d28c91` (do not re-register casually).

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

## Local helpers

```bash
python core/scripts/report_colab_operator_state.py
python core/scripts/report_colab_operator_state.py --state DISCONNECTED
python core/scripts/simulate_colab_operator.py
```

These do not open Colab; they validate config/state policy deterministically.
