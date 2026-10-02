# Cursor Colab Operator Runbook

Orchestration only. Does **not** change Package 4.12.3 benchmark semantics.
Does **not** start Package 4.13. Does **not** re-run rejected FaceID/ReActor tests.

## Operating authority and scope

[AGENTS.md](../AGENTS.md) defines agent-neutral identity, execution, Git, review,
and acceptance policy. This runbook supplies Cursor/browser/CDP procedures only.
All live steps below are conditional on explicit task authority and verified
service identity; reading this procedure grants no authority to execute it.
Google/Drive/browser-profile/GPU/Hugging Face and other service mappings remain
unresolved as recorded in AGENTS.md. Existing sessions, paths, and URLs are not
permission. Stop before service use when authority is unresolved.

Newer accepted architecture decisions take precedence over stale procedures and
configuration. The accepted [PATH C foundation](decisions/identity-architecture-ipadapter-plus-face-foundation.md)
and [license/provenance decision](decisions/identity-architecture-ipadapter-plus-face-license-provenance.md)
block InstantID (`BLOCKED_FOR_COMMERCIAL`) and Characters option 11. The historical
benchmark description below is not execution authority. This policy checkpoint
does not reconcile runtime UI/configuration or change notebook/workflow behavior.

Procedure configuration (subordinate to AGENTS.md and accepted decisions):
[`configs/operator/colab_operator.json`](../configs/operator/colab_operator.json)

State machine: [`core/runtime/colab_operator.py`](../core/runtime/colab_operator.py)

---

## Canonical notebook

When opening Colab is explicitly authorized, open **only** the GitHub-backed
control panel (never a Drive copy as source of truth):

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
| `DISCONNECTED` | Runtime disconnected; Connect requires task authority |
| `CONNECTED` | Runtime connected |
| `REPO_SYNCED` | Repo clone/pull OK; verify the task-authorized SHA |
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

### 0. BEGIN OPERATOR RUN (mandatory)

After the AGENTS.md service and execution gates are satisfied, every authorized
live operator session starts here. A RUNNING local run ID does not itself prove
service permission or GPU/billing authority:

```bash
python core/scripts/colab_operator_control.py begin --checkpoint "<label>"
```

Capture `operator_run_id` from the JSON output. No Chrome launch, checkpoint
helper, probe, monitor, or recovery helper may run before a valid **RUNNING**
`operator_run_id` exists.

Dedicated Chrome:

```bash
python core/scripts/launch_operator_chrome.py --run-id <current-id>
```

Long-running helpers (never direct Agent-terminal `_checkpoint_*` / `_probe_*`):

```bash
python core/scripts/colab_operator_control.py run-helper \
  --run-id <current-id> \
  -- \
  python core/scripts/<helper>.py ...
```

`run-helper` must remain alive as the Job Object containment parent for the
helper's full lifetime (do not spawn-and-exit).

### Background browser policy (mandatory)

Dedicated operator Chrome must **not** steal desktop focus during routine
automation. The user's active desktop window takes priority.

Do **not** automatically use for routine work: `Page.bringToFront`, OS
foreground/activation (`SetForegroundWindow`, taskbar, Alt-Tab), pyautogui /
physical mouse focus clicks, or restore/maximize merely to make Colab visible.

Prefer background-capable paths: CDP `Runtime.evaluate`, DOM inspection, Colab
notebook/kernel APIs, HTTP/ComfyUI probes, filesystem/runtime probes, lifecycle
helpers. A background tab with `document.visibilityState == "hidden"` is valid;
judge health from kernel/HTTP/process/prompt evidence, not visibility.

Foreground only for explicit human-action gates (login, Drive consent, GitHub
trust / Run anyway, 2FA, CAPTCHA, billing/GPU consent, destructive confirmation,
human image review): **STOP** and tell the user what to click — do not
auto-foreground if they can select the window manually.

### A. OPEN

1. Navigate to canonical Colab URL from config (via gated Chrome launcher above).
2. Confirm notebook identity markers.
3. State → `COLAB_OPEN`.

### B. CONNECT

1. If connection is task-authorized and UI shows Connect / Disconnected → click **Connect**.
2. State remains `DISCONNECTED` until connected evidence appears.
3. Wait until Connected (RAM/Disk / “Connected” indicators).
4. Only then: state → `CONNECTED`.

**Do not** treat Connect-click as connected.

### C. ENVIRONMENT

1. Use a GPU runtime only when accelerator use is explicitly task-authorized.
2. If wrong runtime type: **STOP and ask user** before changing billing/GPU (`may_change_gpu_runtime_without_asking=false`).

### D. REPO SYNC

1. Run Repository Sync / bootstrap cells.
2. Verify clone at `/content/ai-studio-colab` matches the task-authorized ref and exact SHA; do not substitute a moving `origin/main` for an authorized checkpoint.
3. State → `REPO_SYNCED`.

### E. RUN NOTEBOOK

The notebook and **Run all** have persistent side effects, including Drive writes,
package/dependency installation, downloads, and service/background work where
enabled. They are not read-only validation. Check explicit task scope for each
effect before execution; do not run a broader sequence than authorized.

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

**Current block:** the InstantID / option-11 benchmark route described here is
historical and blocked by the accepted PATH C decisions above. Do not execute it
or use the advanced raw-execute menu to bypass that block. Preserve license/asset,
billing consent, benchmark-intent, and human-review gates for any future authorized
route. Resolving this conflict requires a separately accepted decision/task.

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
| Historical production identity benchmark | `11` | **BLOCKED** by current PATH C decisions; formerly one-action S1–S4 |
| Status / architecture report | `12` | Report only; capture ≠ production PASS |
| Advanced identity benchmark tools | `13` | Prepare / raw execute / diagnostics; no bypass of PATH C blocks or execution gates |
| Package 4.12.3 consolidated QA | run `python core/scripts/qa_package4123.py` in repo | Offline/sim QA |
| Rejected FaceID/ReActor | **Do not re-run for production** | Status remains rejected |

Historical blocked sequence: **`9` → `13` → `11`**, not top-level `13` → `11`.

Helper: `navigation_sequence("run_production_identity_benchmark")` in `core/runtime/colab_operator.py`.

**GPU confirmation:** The historical menu asks `[y/N]` before GPU work and exposes
`--operator-live-intent`. Neither the flag nor a request to run this blocked
benchmark overrides current PATH C decisions. For any future permitted route,
apply AGENTS.md's explicit GPU/task authority and consent gates. Opening Characters
does not authorize execution; stop for Google/Drive auth, billing, CAPTCHA, or
other human consent gates.

Orchestrator: `core/scripts/run_production_identity_benchmark.py` — emits `status=COMPLETE|HUMAN_REVIEW_REQUIRED|FAILED` plus structured JSON fields (character, scenarios, prompt IDs, durable paths, report paths, consolidated QA).

**Historical blocked-route preflight (reference only):** ComfyUI reachable → InstantID live `/object_info` nodes → structural InstantID readiness → asset hash gates → license gate evaluation → OutputWatcher current-runtime health. Fail closed with actionable messages; never Full Reset. This description does not authorize probes or GPU scenarios.

**Historical after-capture behavior:** invokes Package 4.12.3 consolidated QA (`core.runtime.package4123_qa.run_consolidated_package4123_qa`). Consolidated QA failure forces `FAILED` (never `COMPLETE`). QA is verification evidence, not independent acceptance.

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

### J. CHECKPOINT REPORTING AND INDEPENDENT REVIEW

Prepare a checkpoint report before stopping for review. When the task explicitly
authorizes ledger publication, publish evidence to the **single** GitHub issue titled exactly
`AI Studio Operator Checkpoint Ledger`
([morecolorfulthanHD/ai-studio-colab](https://github.com/morecolorfulthanHD/ai-studio-colab)).

**Order for an authorized ledger publication:**

1. Construct the checkpoint report (template below).
2. Publish **ONE** comment on the ledger issue (`gh issue comment … --body-file`).
3. Confirm publication succeeded (comment URL / issue number). If publish fails →
   write the report locally, state the exact GitHub error, and **STOP**.
4. Then stop for independent exact-SHA GitHub review under AGENTS.md. The comment
   supplies a pointer and supporting evidence; it does not establish acceptance.

If ledger publication is outside task scope, return the checkpoint report without
posting. Independent review must use the canonical repository's exact SHA through
the required project-specific connected GitHub account specified in AGENTS.md.
If that connection is unavailable or ambiguous, review stops. A `review checkpoint`
message, issue comment, copied Codex output, or local state cannot substitute for
that verification.

**Review ZIPs / local handoff packages:** retain them for diagnostics, archival
handoff, and human convenience as supplementary evidence only. Uploaded ZIPs are
not authoritative independent review. Package-building functionality remains
available; creating a package is not acceptance and requires appropriate task scope.

**Hard rules:**

- Do **not** create a new GitHub issue per checkpoint.
- Do **not** use main-branch commits merely to transmit checkpoint reports.
- Do **not** require screenshots for routine checkpoints.
- Do **not** expose secrets/tokens in ledger comments.

```bash
gh issue list --repo morecolorfulthanHD/ai-studio-colab --state open \
  --search "AI Studio Operator Checkpoint Ledger in:title" \
  --json number,title,url

gh issue comment <number> --repo morecolorfulthanHD/ai-studio-colab \
  --body-file <checkpoint.md>
```

**Comment template** (must begin with these fields; end with a JSON block):

~~~~
CHECKPOINT_ID: <UTC ISO8601 or unique id>
CHECKPOINT_TITLE: <short title>
STATUS: PASS | BLOCKED | FAIL | HUMAN_ACTION_REQUIRED
OPERATOR_RUN_ID: <id or n/a> (<status if known>)
REPO_HEAD: <git rev-parse HEAD>
PACKAGE: 4.12.3

SUMMARY:
...

EVIDENCE:
- ...   # live-runtime / research-business / code-checkpoint facts as applicable

BLOCKERS:
- ...

CHANGES:
- repo changes: yes|no
- commit SHA: <sha|n/a>
- temporary files remaining: ...

HUMAN_ACTION:
- ...

NEXT_RECOMMENDED_STEP:
...

```json
{ "checkpoint_id": "...", "title": "...", "status": "...",
  "operator_run_id": "...", "repo_head": "...",
  "evidence": {}, "blockers": [], "human_action": "...",
  "next_recommended_step": "..." }
```
~~~~

**Evidence buckets (include what applies):**

| Bucket | Examples |
|--------|----------|
| Live-runtime | `operator_run_id` / status, Colab connected?, Chrome state, menu path taken, ComfyUI/QA report paths, fail-closed gate hits |
| Research / business | contacts, drafted outreach (subject+body), license conclusions, PATH A/B/C decisions, comparison tables |
| Code checkpoint | files changed, commit SHA or `n/a`, temps remaining, whether Package 4.12.3 semantics were touched |

**Human visual / consent gates only** (ask user; screenshots/interaction may be required):

- Google login / 2FA / passkey
- Drive mount consent
- GitHub trust prompts
- CAPTCHA
- Billing / GPU consent
- Uncertain destructive actions
- `HUMAN_REVIEW_REQUIRED` visual output review

For authorized ledger reporting, routine screenshots are not required. Acceptance
still requires independent exact-SHA GitHub verification and explicit acceptance
by the AI Studio Colab ChatGPT Project.

---

## Restart / reconnect policy

**Only within explicit task authority covering recovery and its side effects:**

- reconnect a disconnected runtime
- rerun startup / Repository Sync cells
- rerun Full Launch after a recoverable runtime death when the runbook path applies

Apply AGENTS.md's separate network, dependency, download, GPU, paid-compute, and
long-running-job gates to recovery too. Retries must not become unbounded spending;
runtime/time/cost limits remain unresolved until separately authorized.

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

After the user resolves the blocker, recheck service identity and task authority
before resuming from the last known state (`AUTH_RESOLVED` → continue sequence).

---

## Recommended Cursor Agent settings (document only)

Do **not** programmatically change user settings. Recommend:

- browser tooling enabled
- auto-run only within an explicitly authorized live task and verified service
  identity; settings do not grant authority for Connect, Run all, or menu execution
- destructive actions still require approval
- auth/consent always user-controlled

---

## Operator cancellation / lifecycle

Machine-local only (`%LOCALAPPDATA%\AI_Studio\operator\` on Windows).

```bash
python core/scripts/colab_operator_control.py begin --checkpoint "LABEL"
python core/scripts/colab_operator_control.py status
python core/scripts/colab_operator_control.py run-helper --run-id <id> -- python core/scripts/<helper>.py
python core/scripts/colab_operator_control.py stop
python core/scripts/colab_operator_control.py stop --close-browser
python core/scripts/colab_operator_control.py clear-stale
python core/scripts/simulate_colab_operator_lifecycle.py
python core/scripts/simulate_operator_job_containment.py
python core/scripts/simulate_operator_run_helper_cli.py
```

**Begin is mandatory** before any Chrome / helper / probe / monitor work.
Capture `operator_run_id` from `begin` JSON.

**Banned for live operator work (direct Agent terminal):**
`_checkpoint_*.py`, `_probe_*.py`, `_diag_*.py`, `_status_*.py`, and other
long-running operator helpers. Use `run-helper` instead. Routine short commands
(`git status`, `git rev-parse`, lifecycle `status`) may run directly if they do
not spawn persistent/background work.

**User stop/pause phrases** (`stop`, `pause`, `stop running`, …) ⇒ immediately
`stop` (preferred while the agent is alive), verify CANCELLED/idle, do **not**
auto-resume or relaunch Chrome. Contained `run-helper` parents notice
cancellation and exit CANCELLED; direct helper Agent terminals should no longer
exist outside those parents. If Cursor UI Stop abruptly kills a `run-helper`
parent, Windows Job Object `KILL_ON_JOB_CLOSE` should reclaim that parent's
contained transient helpers.

Default `stop` prevents Chrome relaunch and kills owned helper processes; it does
**not** close an already-open dedicated Chrome window unless `--close-browser`.
Never kill normal/default-profile Chrome. Never disconnect Colab / Full Reset /
delete Drive / kill remote ComfyUI or OutputWatcher as part of local cancellation.

Local CANCELLED/idle status does not prove remote Colab/ComfyUI execution stopped.
Report that uncertainty; remote inspection or shutdown needs appropriate task
authority. Do not infer that paid compute ended from local operator cleanup.

All operator-owned local children must launch via
`OperatorLifecycle.spawn_owned_helper` / `spawn_operator_process` (central API),
normally through `colab_operator_control.py run-helper` for Cursor sessions.
Transient helpers use Windows Job Object `KILL_ON_JOB_CLOSE` when `contain=True`.
Dedicated Chrome uses `kind=chrome` with containment forced off so parent death /
normal `stop` does not tear down an already-open operator browser.

Dedicated Chrome launch must go through
`python core/scripts/launch_operator_chrome.py --run-id <id>` (gated
`launch_chrome_for_run`). `--run-id` is required.

**Cursor UI Stop limitation:** if Cursor kills the agent abruptly, Python `atexit`
hooks may not run. Mitigation: cooperative cancellation + PID registry + Windows
Job Object `KILL_ON_JOB_CLOSE` for contained helpers owned by a living
`run-helper` parent; helpers self-exit when their `run_id` is cancelled or
superseded.

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
python core/scripts/simulate_operator_run_helper_cli.py
python core/scripts/colab_operator_control.py status
```

These do not open Colab (except the gated Chrome launcher when explicitly used),
but some create local state, reports, or child processes. Inspect each helper's
effects before use; this list is not blanket approval for offline/static checks.
