# AI Studio repository-native wake/orchestration bootstrap

Status: disabled source bootstrap; implementation acceptance and live proof pending.
Authority: [Issue #7](https://github.com/morecolorfulthanHD/ai-studio-colab/issues/7),
under [Goal #2](https://github.com/morecolorfulthanHD/ai-studio-colab/issues/2),
[review #4](https://github.com/morecolorfulthanHD/ai-studio-colab/issues/4), and
[continuation #5](https://github.com/morecolorfulthanHD/ai-studio-colab/issues/5).

## Installation and boundaries

This checkpoint prepares twelve files. It does not merge or activate them.
Committed activation is false; credentialConfirmation, liveAuthority, and scope
are null. Missing, malformed, branch-local, artifact-provided, or forged activation
cannot authorize an agent or publication. The controller reads activation,
Goal/review/continuation Issues, AGENTS.md and architecture decisions at one
fresh canonical main SHA and rejects main races. Every agent invocation and
trusted write/dispatch requires a fresh canonical gate.

Both existing Work automations remain enabled and unchanged. Work owns review
during this bootstrap; its exact-SHA comments under Issue #4 remain valid for
this task. They do not constitute native receipt/App/run provenance. No duplicated
live review ownership is installed. Local PASS logs establish fixture behavior,
not independent acceptance or a working live loop.

PATH C is preserved: InstantID is BLOCKED_FOR_COMMERCIAL, Characters option 11
is blocked, Package 4.13 remains closed. The notebook, Google/Drive/model/download,
runtime, inference, GPU/TPU, paid-compute, external-service, license, consent and
HUMAN_REVIEW_REQUIRED boundaries in AGENTS.md remain in force. No architecture,
product, runtime, credential, or budget decision is transferred from Atlas.

## Roles and event flow

Issue opened/reopened/edited selects a canonical task Issue. The controller
requires owner ID 35986152 and login morecolorfulthanHD, open authorized status,
one concrete contiguous AI_STUDIO authority block, a self-referencing Issue URL,
an existing exact current-main base, a dedicated codex/task-ID branch, and literal
scope. A PR in any state consumes task-start; a branch without a PR requires
reconciliation. Editing or reopening a consumed Issue never restarts it.

PR ready_for_review/synchronize and internal PR dispatch select the exact
current canonical PR. Fork/foreign/draft/closed PRs, mismatched authority, wrong
lineage, out-of-scope diffs and nonregular/executable modes fail closed. Inputs
are wake IDs only; no event payload supplies trusted scope, SHA, decision or
authority. Native review-completion, internal review-run dispatch and authenticated
comment fallbacks resolve the actual source receipt.

The workspace implementation worker proposes a bounded patch and emits
VERIFICATION_PENDING, HUMAN_REQUIRED or AUTHORITY_BLOCKED. It does not publish or
self-accept. The reviewer emits schema-constrained exact-SHA decisions. Both use
official openai/codex-action@v1 with :workspace / :read-only and drop-sudo,
read-only GitHub job permissions, no write token, and no custom endpoint/PAT.
OPENAI_API_KEY occurs only as the Action input in the disabled future path.

Isolated verification reconstructs the patch in a clean exact-parent checkout,
checks scope/file modes/diff whitespace, syntax and the three orchestration
suites. It uses only a sanitized nonsecret environment and standard Node/Git.
There is no dependency installation, arbitrary Issue QA command, baseline waiver,
application QA, notebook import, or candidate execution with a write token.

A separately privileged publisher executes controller code pinned to canonical
main. It rechecks authority/HEAD/source before additive commit and normal push,
requires successful same-run verifier provenance, exact patch/result/plan/contract/
tree/run/attempt bindings and complete passing evidence. Failed, incomplete,
altered or racing candidates publish nothing. Agents never receive that token.
No force push, amend, rebase, squash, merge, replacement PR, or continuation Issue
creation is implemented.

Publication creates one draft PR, or updates the same correction PR, confirms
pushed HEAD, marks it ready, and explicitly redispatches independent review on
main because GITHUB_TOKEN-authored events can be suppressed.

## Native correction receipt and dispatch

The review publisher posts one actual decision comment and uploads receipt.json.
The immutable artifact transport digest is checked before parsing; only that
one archive entry is accepted. The receipt binds repository, contract hash, task,
exact reviewed SHA, PR, controller SHA, actual comment ID/body/hash, run and
attempt, timestamps, and literal in-scope corrections.

Correction requires completed successful canonical independent-review source,
matching workflow definition, gate/reviewer/publish-review successful jobs from
the actual attempt, github-actions bot ID 41898282 and App provenance on the
actual comment, unexpired artifact/receipt, unchanged HEAD/authority, no processed
source, and a maximum of one automatic correction. Username/copy strings and
Work comments alone cannot supply native receipt evidence.

After successful review workflow completion, the implementation workflow's
trusted dispatch-correction job reloads source provenance and the uploaded
receipt, then explicitly dispatches implementation with review_run only.
workflow_run and issue_comment are fallbacks. Source/branch concurrency and fresh
HEAD/processed guards reject duplicate successful publication. ACCEPTED and
HUMAN_REQUIRED never dispatch correction. There is no unbounded polling or retry.
Failure after a branch push but before PR/marker/dispatch is reconciliation,
not permission to guess a restart.

## Later human gates

1. Independent exact-SHA Work acceptance of this disabled checkpoint.
2. Later durable exact-SHA merge authority; Issue #7 withholds merge.
3. Human confirmation that the AI Studio-specific Actions OPENAI_API_KEY is
   configured. Never request, inspect, copy, log or commit the value.
4. Separately authorized task-only native live authority, bound to the exact task
   contract hash, expiry, finite invocation count, positive cost ceiling, and
   explicit confirmation of an enforced key/project budget cap. A confirmation
   alone grants no paid execution.
5. Separate exact-SHA activation/installation authority and one bounded proof of
   task-start, reviewer wake, real receipt publication, one harmless in-scope
   CHANGES_REQUESTED correction on the same PR/branch, review redispatch, and
   terminal behavior.
6. Only after accepted proof may a new scoped task consider broader task-loop
   support or transition review ownership. General authorized-task-loop activation
   is deliberately unsupported here. Existing Work tasks stay enabled.

The future strict authority markers resolved from owner-authored same-repository
Issues are AI_STUDIO_OPENAI_SECRET_CONFIRMED, AI_STUDIO_CODEX_LIVE_AUTHORIZED,
AI_STUDIO_CODEX_LIVE_SCOPE (task:ID), AI_STUDIO_LIVE_TASK_CONTRACT_HASH,
AI_STUDIO_MAX_AGENT_INVOCATIONS, AI_STUDIO_MAX_COST_USD,
AI_STUDIO_LIVE_EXPIRES_AT and AI_STUDIO_BUDGET_CAP_CONFIRMED. These name future
requirements; this document grants none. Native run inventory conservatively
counts every orchestration run since the live grant as an invocation reservation,
including skipped runs; no claim of actual dollar telemetry is made.

The bootstrap supports only the explicit orchestration offline verification
profile. Other verification profiles or external task actions need a subsequent
bounded source/authority task. Live GitHub/Action integration, actual budget-cap
operation and uninterrupted wake behavior remain unproven.

## Authorized local verification

Run Node syntax checks for the two new .mjs modules and:

    node --test tests/ai-studio-orchestration/*.test.mjs

Parse both workflow YAMLs and both result JSON schemas with already installed
offline tooling; inspect job permissions, pinned controller paths, dependencies,
artifact names, and schema paths. Run git diff --check and value-suppressed secret
pattern checks. No package acquisition or workflow/API/model dispatch is needed.

The tests use self-contained mocked canonical connectors and dispatch callbacks,
plus disposable local bare Git repositories without credentials, hooks or network.
The miniature subprocess verifier fixture tests actual patch reconstruction,
syntax/test output and race rejection. Its three miniature tests are not the
repository suite; the top-level command runs all three real safety suites.
Shared policy fixtures register policy tests when imported by other suites, so
the reported total includes those independent executions.

Read-only design references: opportunity-os at
cc5f4733186e5124afd8f4526c94e46a8566ee48, its Atlas wake document, ADR-026 and two
native workflows. Their product logic, activation values, credentials, baseline
waivers, acceptance and live-proof claims are not copied.
