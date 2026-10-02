# AI Studio Colab repository operating policy

## Authority and roles

This file is the durable, editor-neutral operating-policy authority. Cursor is
not required for Codex or ChatGPT operation. Apply this hierarchy:

1. **AGENTS.md:** identity, role separation, execution authority, Git/review gates,
   service-account ambiguity, and artifact/acceptance rules.
2. **Architecture and decision records:** architecture and promoted technical decisions.
3. **[Operator runbook](docs/cursor-colab-operator.md):** concrete Chrome/CDP/Colab/runtime procedures.
4. **Tool adapters**, including `.cursor/rules/ai-studio-colab-operator.mdc`:
   pointers and tool-specific procedure; no independent durable governance.

Newer accepted architecture/decision records take precedence over older tool,
runbook, and configuration descriptions. If a lower-level instruction conflicts
with this policy or a newer accepted decision, stop and report the conflict.

The **AI Studio Colab ChatGPT Project** is the architect, research/planning
authority, specification authority, acceptance authority, and independent reviewer.
**Codex** implements, modifies the repository, performs authorized verification,
and produces checkpoints. **GitHub** is the authoritative implementation-review
interchange. Implementation, simulation, notebook, QA, ZIP, or runtime success
does not establish acceptance.

## Repository and identity

- Canonical repository: `morecolorfulthanHD/ai-studio-colab`.
- Dedicated workspace: `C:\Projects\AI-Studio-Colab-Codex`.
- GitHub account: `morecolorfulthanHD`.
- Expected remote: `git@github-morecolorfulthanHD:morecolorfulthanHD/ai-studio-colab.git`.
- SSH host alias: `github-morecolorfulthanHD`; verify it authenticates as the
  project account, separately from the Git author.
- Git author: `morecolorfulthanHD <morecolorfulthanhidef@gmail.com>`.
- Required connected ChatGPT/GitHub review account:
  `morecolorfulthanHD` / `morecolorfulthanhidef@gmail.com`.

Before Git writes, verify the canonical repository, remote, exact authorized
base, isolated worktree path, branch, working-tree state, author, and
repository-scoped SSH identity. Stop before mutation if repository, identity,
lineage, working-tree, authority, environment, or architectural preconditions
differ from the task handoff. If sandbox isolation prevents host Git/SSH checks,
request host-side read-only verification; do not change ownership,
`safe.directory`, SSH configuration, credentials, or global Git configuration.

## Git and independent acceptance gates

Fetch and verify the exact task-authorized base. Implement only in an isolated
branch/worktree from that base, never directly on `main`. Codex may commit and
push an explicitly authorized checkpoint branch using an ordinary fast-forward
push. No force-push or merge without separate authorization.

For the repository-policy-v1 checkpoint, the authorized base is exactly
`33f03dba2977dc9468b1eea40f095cbdd0bac355`, and the branch is
`codex/ai-studio-colab-repo-policy-v1`. Future tasks must specify their own base
and scope; this historical base does not authorize future implementation.

Independent review must verify the **exact Git SHA in the canonical GitHub
repository through the required project-specific connected GitHub account**.
When multiple accounts are connected, explicitly select
`morecolorfulthanHD` / `morecolorfulthanhidef@gmail.com`; never rely on an
arbitrary/default connection. If that connection is unavailable, ineligible,
ambiguous, or cannot access the repository, stop review. Another linked account,
public GitHub access, copied Codex output, local filesystem state, and uploaded
ZIPs cannot substitute for it.

A checkpoint is accepted only when the AI Studio Colab ChatGPT Project
independently verifies and explicitly accepts that exact SHA. Acceptance is
separate from merge and grants no notebook, hosted runtime, GPU, deployment,
service mutation, or spending authority. Issue comments and checkpoint reports
can point reviewers to evidence; they do not replace independent verification.
Publish ledger comments only when the task authorizes that communication.

## External service authority

For this checkpoint, only the GitHub account and canonical repository above have
fully verified external project identity. Ownership/permission mappings remain
**unresolved** for Google Colab, Google Drive, Google account/browser profile,
hosted GPU runtime, Hugging Face, ComfyUI runtime, A1111 runtime, external tunnels,
remote notebook sessions, and paid compute.

Before a task uses any such service, verify its account/project/runtime authority.
If identity or permission is unresolved or ambiguous, stop before use. Paths,
notebook metadata, comments, URLs, publisher names, previously used browser
sessions, and Drive mount locations do not establish authority. Service-account
identity must be verified separately from repository identity.

## Notebook, runtime, GPU, and cost gates

Repository inspection and task-authorized local static/offline checks are distinct
from hosted notebook execution. The canonical notebook has persistent side
effects; opening/running it or using **Run all** is not read-only validation.

Explicit task authority is required for opening/running Colab, Run all, mounting
Drive, creating Drive directories, installing packages, cloning dependencies,
downloading models or datasets, starting ComfyUI/A1111, background/watchdog
processes, output synchronization, inference submission, GPU/TPU or other
accelerator execution, browser-authenticated Google sessions, and hosted runtime
restart/reset. Network access, model/data downloads, upstream package/dependency
execution, GPU usage, and paid compute are separate execution gates.

GPU/accelerator execution, paid compute, model/data downloads, and long-running
jobs each require explicit task authority. Preserve benchmark-intent, billing
consent, license/asset fail-closed, and human-review safeguards. Auth/consent and
`HUMAN_REVIEW_REQUIRED` gates must not be bypassed. Retries must not become
unbounded autonomous spending. Exact runtime/time/cost limits remain unresolved
until separately authorized; this checkpoint invents no budgets.

Local operator cancellation does not prove remote Colab/ComfyUI execution has
stopped. Report that uncertainty and obtain appropriate authority for remote
inspection or shutdown; local cancellation does not authorize destructive resets
or Drive deletion.

## Current architecture conflict

Older operator guidance/configuration describes InstantID / Characters option 11
as a normal benchmark route. The newer accepted
[PATH C foundation decision](docs/decisions/identity-architecture-ipadapter-plus-face-foundation.md)
and [license/provenance decision](docs/decisions/identity-architecture-ipadapter-plus-face-license-provenance.md)
control: InstantID is `BLOCKED_FOR_COMMERCIAL`, Characters option 11 is blocked,
and Package 4.13 remains closed. Older descriptions and helpers are not execution
authority. Do not weaken these gates or silently substitute another architecture.
Policy integration does not change notebook behavior, runtime code, configuration,
model architecture, or workflow execution semantics. Reconciliation needs a later
scoped task.

## Artifact authority

| Level | Artifact | Authority |
| --- | --- | --- |
| 1 | Canonical committed source/config/notebook/workflow definitions | Implementation source of truth |
| 2 | Prepared workflows | Generated/prepared intent; not evidence of execution |
| 3 | Executed workflow snapshots | Evidence of what executed; not automatically accepted results |
| 4 | Notebook saved outputs | Historical/editorial runtime evidence; not automatically current or accepted |
| 5 | Generated QA reports / PASS reports | Verification evidence; not independent acceptance |
| 6 | Review ZIPs / local handoff packages | Supplementary diagnostics, archival handoff, or human convenience only; never authoritative repository verification |
| 7 | Models, datasets, checkpoints, caches, logs, downloaded files | External/local runtime artifacts; not canonical source unless explicitly promoted under separate authority |
| 8 | Accepted checkpoint/result | Exact Git SHA independently reviewed and explicitly accepted by the AI Studio Colab ChatGPT Project |

Uploaded ZIPs, local packages, and copied Codex output cannot establish independent
checkpoint verification. Preserve review-package functionality as supplementary
evidence. A clean Git worktree does not prove ignored runtime, Drive, or generated
artifacts are absent.

## Secrets and credentials

Secrets, tokens, private keys, API keys, Google credentials, Hugging Face tokens,
and account credentials must remain outside Git. Do not print or reproduce
discovered secret values or persist new credentials to repository files. Do not
assume `.env` exclusions protect all credential formats.

Known unresolved hardening item: notebook settings can persist an `hf_token` in
plaintext on Drive. This governance checkpoint does not change credential
handling; remediation requires a later scoped task.

## External triggers and verification

Inspection at the policy-v1 base found no tracked GitHub Actions workflows, no
active Git hooks, and no configured `core.hooksPath`.
`scripts/pre_push_qa.sh` is a runnable convention, not an installed hook.
These observations are not permanent guarantees. Source-tree absence does not
prove absence of GitHub Apps, webhooks, repository rulesets, hosted integrations,
external schedulers, or machine-level automation. Inspect GitHub-visible
status/check/workflow behavior after checkpoint pushes. Do not create CI or
automation as part of this policy checkpoint.

For governance-only work, use repository-safe offline/static checks and
`git diff --check`. Inspect QA scripts before use; do not run checks that execute
notebooks, install dependencies, download models/data, call external APIs, start
browser/runtime services, mount Drive, or invoke GPU compute without authority.

## Deferred work

Separate scoped tasks must address operator config InstantID/PATH C reconciliation,
notebook repository-sync validation, credential persistence, Hugging Face URL/token
handling, runtime/download/budget controls, dependency pinning claims, stale
phase/validation-SHA documentation, review-package helper wording, notebook-output
acceptance labeling, and latest-report overwrite behavior. Do not silently include
those changes in governance work.
