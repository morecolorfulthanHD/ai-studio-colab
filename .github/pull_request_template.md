<!--
Replace every placeholder from the explicitly authorized durable GitHub task contract.
Do not retain AI_STUDIO_REVIEW_AUTHORIZED: true for an unauthorized task.
Use exactly one complete block; its values must exactly match that contract.
-->
```text
AI_STUDIO_REVIEW_AUTHORIZED: true
AI_STUDIO_TASK_ID: <stable task id>
AI_STUDIO_AUTHORIZED_BASE: <full commit SHA>
AI_STUDIO_IMPLEMENTATION_BRANCH: <branch name>
AI_STUDIO_SPEC_AUTHORITY: <durable GitHub task-contract reference>
```

## Governing Goal

https://github.com/morecolorfulthanHD/ai-studio-colab/issues/2

## Implementation summary

<!-- Describe the authorized problem, resulting behavior, and durable task reference. -->

## Exact checkpoint SHA

<!-- Full current pushed PR HEAD SHA. Update on every additive checkpoint. -->

## Files changed

<!-- List exact paths and explain how each stays inside authorized scope. -->

## Verification performed

<!-- List authorized checks and their results. PASS is evidence, not acceptance. -->

## Known waivers/exceptions

<!-- State none, or cite explicit durable authority. Do not invent waivers. -->

## Automatic integration/deployment observations

<!-- Inspect GitHub-visible statuses, checks, workflows, and deployments after push
and before any authorized merge. Record evidence and unexpected side effects. -->

## Unresolved issues

<!-- State none, or identify blockers and the smallest required human decision. -->

## Prohibited-action confirmation

<!-- Confirm compliance with the task's prohibited actions and current AGENTS.md.
Preserve PATH C: InstantID is BLOCKED_FOR_COMMERCIAL, Characters option 11 is
blocked, and Package 4.13 remains closed. -->

## Separate action authority

<!-- State none or cite explicit durable authority and satisfied conditions for
merge, deployment, runtime activation, or other separately gated actions. -->

## Independent review protocol

- Authorization is never inferred from title, labels, CI, implementation claims,
  notebook outputs, QA PASS reports, ZIPs, or runtime success.
- Independent review applies only to the exact current PR HEAD SHA in the canonical
  repository through the explicitly selected required GitHub connection:
  `morecolorfulthanHD / morecolorfulthanhidef@gmail.com`.
- Each decision must contain `AI_STUDIO_DECISION`, immediately followed by
  `REVIEWED_SHA: <full SHA>` and `AI_STUDIO_TASK_ID: <task id>`, matching this task
  and current PR HEAD. Never carry acceptance from an older SHA to a newer SHA.
- `AI_STUDIO_DECISION: ACCEPTED` does not imply notebook/runtime/GPU/external-service
  authority. Acceptance and merge remain separate unless the durable task contract
  explicitly authorizes merge.
- `AI_STUDIO_DECISION: CHANGES_REQUESTED` corrections remain on the same PR and
  branch when in scope. Implement additively, run authorized verification, push
  normally, update the checkpoint SHA, and return this PR to review.
- `AI_STUDIO_DECISION: HUMAN_REQUIRED` is used only for genuine new human authority.
  Stop and report the task ID, exact SHA, PR, precise blocker, and smallest human
  decision required. Stop for missing, inconsistent, inaccessible, or superseded
  durable authority; do not work around a gate.
- Keep this PR draft until implementation and authorized verification are complete,
  the checkpoint is pushed, the working tree is clean, PR HEAD equals the reported
  checkpoint SHA, and no known implementation blocker remains.
- Preserve published history. Do not amend, rebase, reset, replace, or force-push a
  published checkpoint unless the exact durable task contract explicitly permits it.
