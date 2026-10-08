import { createHash } from 'node:crypto';

export const REPOSITORY = 'morecolorfulthanHD/ai-studio-colab';
export const OWNER = 'morecolorfulthanHD';
export const OWNER_ID = 35986152;
export const BOT_ID = 41898282;
export const REVIEW_WORKFLOW = '.github/workflows/ai-studio-independent-review.yml';
export const IMPLEMENTATION_WORKFLOW = '.github/workflows/ai-studio-implementation.yml';
export const AUTHORITY_PATHS = [
  'AGENTS.md', 'docs/architecture.md',
  'docs/decisions/identity-architecture-ipadapter-plus-face-foundation.md',
  'docs/decisions/identity-architecture-ipadapter-plus-face-license-provenance.md',
];
export const BOOTSTRAP_PATHS = [
  '.github/workflows/ai-studio-implementation.yml',
  '.github/workflows/ai-studio-independent-review.yml',
  'tools/ai-studio-orchestration/activation.json',
  'tools/ai-studio-orchestration/policy.mjs',
  'tools/ai-studio-orchestration/controller.mjs',
  'tools/ai-studio-orchestration/implementation-schema.json',
  'tools/ai-studio-orchestration/review-schema.json',
  'tests/ai-studio-orchestration/policy.test.mjs',
  'tests/ai-studio-orchestration/publication.test.mjs',
  'tests/ai-studio-orchestration/correction-dispatch.test.mjs',
  'docs/ai-studio-autonomous-wake-orchestration.md',
  'docs/decisions/ai-studio-github-native-codex-wake.md',
];
export const SHA = /^[0-9a-f]{40}$/;
export const hash = value => createHash('sha256').update(typeof value === 'string' || Buffer.isBuffer(value) ? value : JSON.stringify(value)).digest('hex');
export function requireThat(condition, reason) {
  if (!condition) throw new Error('AUTHORITY_BLOCKED: ' + reason);
}
export function oneLine(body, key) {
  const lines = body.split(/\r?\n/).filter(line => line.startsWith(key + ':'));
  requireThat(lines.length === 1, 'missing/repeated ' + key);
  const value = lines[0].slice(key.length + 1).trim();
  requireThat(value && !/[<>]/.test(value), 'placeholder ' + key);
  return value;
}
export function authorityBlock(body, review = false) {
  requireThat(typeof body === 'string', 'inaccessible contract');
  const keys = ['AI_STUDIO_TASK_ID', 'AI_STUDIO_AUTHORIZED_BASE', 'AI_STUDIO_IMPLEMENTATION_BRANCH', 'AI_STUDIO_SPEC_AUTHORITY'];
  const values = keys.map(key => oneLine(body, key));
  const [taskId, base, branch, spec] = values;
  requireThat(/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(taskId), 'task ID');
  requireThat(SHA.test(base), 'exact base');
  requireThat(branch === 'codex/' + taskId, 'dedicated branch');
  requireThat(new RegExp('^https://github\\.com/' + REPOSITORY + '/issues/[1-9][0-9]*$').test(spec), 'same-repository spec');
  const block = keys.map((key, index) => key + ': ' + values[index]).join('\n');
  requireThat(body.replace(/\r/g, '').includes(block), 'mixed/noncontiguous authority block');
  if (review) {
    requireThat(oneLine(body, 'AI_STUDIO_REVIEW_AUTHORIZED') === 'true', 'review unauthorized');
    requireThat(body.replace(/\r/g, '').includes('AI_STUDIO_REVIEW_AUTHORIZED: true\n' + block), 'review block order');
  }
  return { taskId, base, branch, spec };
}
export function taskContract(issue) {
  requireThat(issue?.repository === REPOSITORY && issue.state === 'open' && !issue.pull_request, 'task repository/state');
  requireThat(issue.user?.id === OWNER_ID && issue.user.login === OWNER, 'owner-authored task');
  requireThat(oneLine(issue.body, 'STATUS') === 'AUTHORIZED FOR IMPLEMENTATION', 'task status');
  const a = authorityBlock(issue.body);
  requireThat(a.spec === 'https://github.com/' + REPOSITORY + '/issues/' + issue.number, 'self-reference');
  requireThat(issue.body.includes('https://github.com/' + REPOSITORY + '/issues/2'), 'Goal reference');
  for (const heading of ['Implementation scope', 'Acceptance criteria', 'Allowed verification', 'Prohibited actions']) {
    requireThat(issue.body.includes('## ' + heading), 'missing ' + heading);
  }
  requireThat(/## Human gates/.test(issue.body), 'missing human gates');
  const scope = issue.body.split('## Implementation scope\n')[1]?.split('\n## ')[0];
  const paths = [...(scope ?? '').matchAll(/^- ([.a-zA-Z0-9_/-]+)$/gm)].map(m => m[1]);
  requireThat(paths.length > 0 && new Set(paths).size === paths.length && paths.every(literalPath), 'literal path scope');
  // This bootstrap supports only explicit offline verification profiles. Prose never becomes a command.
  const verification = issue.body.split('## Allowed verification' + '\n')[1]?.split('\n## ')[0] ?? '';
  const profile = verification.includes('node --test tests/ai-studio-orchestration/*.test.mjs') ? 'orchestration' : null;
  requireThat(profile, 'unsupported verification profile');
  return { ...a, issue: issue.number, paths, verificationProfile: profile, contractHash: hash(issue.body) };
}
export function literalPath(path) {
  return typeof path === 'string' && /^[.a-zA-Z0-9_/-]+$/.test(path) &&
    !path.startsWith('/') && !path.endsWith('/') && !path.split('/').some(x => !x || x === '.' || x === '..' || x === '.git') &&
    !path.includes('*');
}
export function canonicalState(s) {
  requireThat(s?.repository === REPOSITORY && s.ownerId === OWNER_ID && SHA.test(s.mainSha), 'canonical repository/main');
  for (const n of [2, 4, 5]) {
    requireThat(s.authorities?.[n]?.state === 'open' && s.authorities[n].user?.id === OWNER_ID &&
      oneLine(s.authorities[n].body, 'STATUS') === 'ACTIVE', 'inactive authority ' + n);
  }
  requireThat(AUTHORITY_PATHS.every(path => typeof s.files?.[path] === 'string' && s.files[path]), 'missing canonical policy');
  requireThat(s.files[AUTHORITY_PATHS[2]].includes('BLOCKED_FOR_COMMERCIAL') &&
    s.files[AUTHORITY_PATHS[3]].includes('BLOCKED_FOR_COMMERCIAL'), 'PATH C policy');
  return hash({ mainSha: s.mainSha, authorities: s.authorities, files: s.files, activation: s.activation, grants: s.grants });
}
export function liveGate(s, task) {
  canonicalState(s);
  const a = s.activation;
  requireThat(a?.version === 1 && Object.keys(a).every(k => ['version','repository','account','liveAuthorized','scope','credentialConfirmation','liveAuthority','maxCorrections'].includes(k)), 'activation schema');
  requireThat(a && a.repository === REPOSITORY && a.account === OWNER && a.liveAuthorized === true, 'activation disabled/missing/malformed');
  requireThat(a.scope === 'task:' + task.taskId && a.maxCorrections === 1, 'bounded task-only live scope');
  for (const [field, marker] of [
    ['credentialConfirmation', 'AI_STUDIO_OPENAI_SECRET_CONFIRMED'],
    ['liveAuthority', 'AI_STUDIO_CODEX_LIVE_AUTHORIZED'],
  ]) {
    const ref = a[field];
    requireThat(typeof ref === 'string' && new RegExp('^https://github\\.com/' + REPOSITORY + '/issues/[1-9][0-9]*$').test(ref), 'durable ' + field);
    const grant = s.grants?.[ref];
    requireThat(grant?.state === 'open' && grant.user?.id === OWNER_ID && grant.user.login === OWNER &&
      oneLine(grant.body, marker) === 'true' &&
      oneLine(grant.body, 'AI_STUDIO_CODEX_LIVE_SCOPE') === a.scope, 'unverified ' + field);
  }
  const grant = s.grants[a.liveAuthority];
  requireThat(oneLine(grant.body, 'AI_STUDIO_LIVE_TASK_CONTRACT_HASH') === task.contractHash, 'live contract hash');
  const limits = {
    maxAgentInvocations: Number(oneLine(grant.body, 'AI_STUDIO_MAX_AGENT_INVOCATIONS')),
    maxCostUSD: Number(oneLine(grant.body, 'AI_STUDIO_MAX_COST_USD')),
    expiresAt: oneLine(grant.body, 'AI_STUDIO_LIVE_EXPIRES_AT'),
  };
  requireThat(Number.isSafeInteger(limits.maxAgentInvocations) && limits.maxAgentInvocations > 0 &&
    Number.isFinite(limits.maxCostUSD) && limits.maxCostUSD > 0 &&
    Date.parse(limits.expiresAt) > s.now, 'missing/expired invocation and spending limits');
  requireThat(s.invocations < limits.maxAgentInvocations, 'invocation bound');
  // An exact execution grant and externally enforced budget must be verified before native paid use.
  requireThat(s.budget?.enforced === true && s.budget.authority === a.liveAuthority &&
    s.budget.remainingUSD > 0 && s.budget.limitUSD <= limits.maxCostUSD, 'unverified spending enforcement');
  return limits;
}
export function validateChanges(task, changes) {
  requireThat(Array.isArray(changes) && changes.length > 0 && changes.length <= task.paths.length, 'empty/unbounded changes');
  for (const change of changes) {
    requireThat(task.paths.includes(change.path) && literalPath(change.path) && !change.oldPath, 'out-of-scope/rename');
    requireThat(['100644', '000000'].includes(change.oldMode) &&
      ['100644', '000000'].includes(change.newMode) && !(change.oldMode === '000000' && change.newMode === '000000'), 'symlink/executable/submodule mode');
  }
}
export function validatePR(s, task) {
  const p = s.pr;
  requireThat(p && p.state === 'open' && !p.draft && p.base.repo.full_name === REPOSITORY &&
    p.head.repo.full_name === REPOSITORY && !p.head.repo.fork && p.base.ref === 'main' &&
    p.head.ref === task.branch && SHA.test(p.head.sha), 'foreign/fork/draft/closed PR');
  requireThat(JSON.stringify(authorityBlock(p.body, true)) === JSON.stringify(authorityBlock(s.task.body)), 'PR contract mismatch');
  requireThat(s.lineage?.base === task.base && s.lineage?.head === p.head.sha && s.lineage?.ancestor === true, 'wrong lineage');
  validateChanges(task, s.changes);
}
export function decisions(s, task) {
  const relevant = [];
  for (const c of s.comments ?? []) {
    const m = c.body?.match(/^AI_STUDIO_DECISION: (ACCEPTED|CHANGES_REQUESTED|HUMAN_REQUIRED)\nREVIEWED_SHA: ([a-f0-9]{40})\nAI_STUDIO_TASK_ID: ([a-z0-9-]+)(?:\n|$)/);
    if (m && m[3] === task.taskId && m[2] === s.pr?.head.sha &&
        (c.user?.id === OWNER_ID || c.user?.id === BOT_ID && c.performed_via_github_app?.slug === 'github-actions')) {
      relevant.push({ decision: m[1], sha: m[2], comment: c });
    }
  }
  requireThat(relevant.length <= 1, 'duplicate/conflicting task-SHA decisions');
  return relevant;
}
export function taskStartPlan(s) {
  canonicalState(s);
  const task = taskContract(s.task);
  requireThat(s.baseCommit?.sha === task.base && s.baseCommit.exists === true && task.base === s.mainSha, 'nonexistent/stale task base');
  requireThat(!s.taskPRs?.length, 'task PR already exists in some state');
  requireThat(!s.branch, 'orphan branch: reconcile, never restart');
  liveGate(s, task);
  return { kind: 'start', task, sha: task.base, pr: null, controllerSha: s.mainSha, authorityHash: canonicalState(s) };
}
export function reviewPlan(s) {
  canonicalState(s);
  const task = taskContract(s.task);
  validatePR(s, task);
  requireThat(decisions(s, task).length === 0, 'decision already exists');
  liveGate(s, task);
  return { kind: 'review', task, sha: s.pr.head.sha, pr: s.pr.number, controllerSha: s.mainSha, authorityHash: canonicalState(s) };
}
export function validateReviewReceipt(s, task) {
  const r = s.receipt, source = s.source;
  requireThat(r?.version === 1, 'receipt schema version');
  requireThat(r && source && source.repository === REPOSITORY && source.path === REVIEW_WORKFLOW &&
    source.status === 'completed' && source.conclusion === 'success' && ['pull_request', 'workflow_dispatch'].includes(source.event) &&
    source.headRepository === REPOSITORY && source.controllerSha === s.mainSha &&
    source.workflowHash === hash(s.files[REVIEW_WORKFLOW]) &&
    ['morecolorfulthanHD', 'github-actions[bot]'].includes(source.actor), 'foreign/failed source review');
  requireThat(source.jobs?.length && ['gate', 'reviewer', 'publish-review'].every(name =>
    source.jobs.filter(j => j.name === name && j.attempt === source.attempt && j.conclusion === 'success').length === 1), 'source job/attempt');
  requireThat(s.artifact?.name === 'ai-studio-review-receipt' && s.artifact.runId === source.id &&
    s.artifact.attempt === source.attempt && !s.artifact.expired && s.artifact.sha256 === hash(r), 'missing/altered/expired receipt artifact');
  requireThat(r.repository === REPOSITORY && r.taskId === task.taskId && r.contractHash === task.contractHash &&
    r.reviewedSha === s.pr.head.sha && r.pr === s.pr.number && r.runId === source.id &&
    r.attempt === source.attempt && r.controllerSha === s.mainSha, 'receipt binding');
  const actual = s.comments.find(c => c.id === r.commentId);
  requireThat(actual && actual.user?.id === BOT_ID && actual.performed_via_github_app?.slug === 'github-actions' &&
    actual.body === r.commentBody && hash(actual.body) === r.commentHash, 'spoofed/comment binding');
  requireThat(Date.parse(r.expiresAt) > s.now && Date.parse(r.createdAt) <= s.now, 'stale receipt');
  return r;
}
export function correctionPlan(s) {
  canonicalState(s);
  const task = taskContract(s.task);
  validatePR(s, task);
  const decision = decisions(s, task)[0];
  requireThat(decision?.decision === 'CHANGES_REQUESTED', 'terminal/missing decision');
  const r = validateReviewReceipt(s, task);
  requireThat(r.commentId === decision.comment.id, 'wrong source decision');
  requireThat(!s.processed?.includes(r.commentId) && s.correctionCount < 1, 'duplicate/correction bound');
  requireThat(Array.isArray(r.corrections) && r.corrections.length > 0 &&
    r.corrections.every(c => task.paths.includes(c.path) && c.requirement && c.verification === task.verificationProfile), 'out-of-scope corrections');
  liveGate(s, task);
  return { kind: 'correct', task, sha: s.pr.head.sha, pr: s.pr.number, source: { runId: r.runId, attempt: r.attempt, commentId: r.commentId },
    controllerSha: s.mainSha, authorityHash: canonicalState(s) };
}
export function planEvent(s, event) {
  requireThat(event.repository === REPOSITORY && [OWNER, 'github-actions[bot]'].includes(event.actor), 'event repository/actor');
  if (event.name === 'issues' && ['opened', 'reopened', 'edited'].includes(event.action)) return taskStartPlan(s);
  if (event.name === 'pull_request' && ['ready_for_review', 'synchronize'].includes(event.action)) return reviewPlan(s);
  if (event.name === 'workflow_dispatch' && event.pr) return reviewPlan(s);
  if (event.name === 'workflow_dispatch' && event.issue) return taskStartPlan(s);
  if (event.name === 'workflow_run' || event.name === 'issue_comment' || event.name === 'workflow_dispatch' && event.reviewRun) return correctionPlan(s);
  throw new Error('AUTHORITY_BLOCKED: unsupported event');
}
export function revalidate(plan, s) {
  const fresh = plan.kind === 'start' ? taskStartPlan(s) : plan.kind === 'review' ? reviewPlan(s) : correctionPlan(s);
  requireThat(hash(plan) === hash(fresh), 'racing HEAD/authority/source');
  return fresh;
}
export function verificationReceipt(plan, patch, result, tree, context, checks) {
  return { version: 1, repository: REPOSITORY, planHash: hash(plan), contractHash: plan.task.contractHash,
    patchHash: hash(patch), resultHash: hash(result), tree, controllerSha: plan.controllerSha,
    runId: context.runId, attempt: context.attempt, checks };
}
export function publicationPlan(plan, s, candidate) {
  revalidate(plan, s);
  requireThat(candidate.result?.status === 'VERIFICATION_PENDING', 'worker cannot self-verify/accept');
  requireThat(candidate.parent === plan.sha && SHA.test(candidate.tree), 'exact additive parent/tree');
  validateChanges(plan.task, candidate.changes);
  const v = candidate.verification;
  requireThat(v?.version === 1 && v.repository === REPOSITORY && v.planHash === hash(plan) &&
    v.contractHash === plan.task.contractHash && v.patchHash === hash(candidate.patch) &&
    v.resultHash === hash(candidate.result) && v.tree === candidate.tree && v.controllerSha === plan.controllerSha &&
    v.runId === candidate.runId && v.attempt === candidate.attempt, 'verification binding');
  requireThat(candidate.verifier?.name === 'verify-implementation' && candidate.verifier.conclusion === 'success' &&
    candidate.verifier.attempt === candidate.attempt, 'verifier provenance');
  requireThat(Array.isArray(v.checks) && v.checks.length === 2 &&
    ['syntax', 'orchestration-tests'].every(name => v.checks.filter(x => x.name === name && x.exitCode === 0 &&
      x.failed === 0 && Number.isSafeInteger(x.passed) && x.passed > 0 && /^[a-f0-9]{64}$/.test(x.logHash)).length === 1), 'incomplete/failed verification');
  return { branch: plan.task.branch, parent: plan.sha, tree: candidate.tree, pr: plan.pr,
    reviewDispatch: { workflow: REVIEW_WORKFLOW, ref: 'main', inputs: { pr: plan.pr } }, source: plan.source ?? null };
}
export function publishedCheckpointGate(plan, s, checkpoint) {
  canonicalState(s);
  const task = taskContract(s.task);
  requireThat(task.contractHash === plan.task.contractHash && s.mainSha === plan.controllerSha &&
    canonicalState(s) === plan.authorityHash, 'post-push authority race');
  liveGate(s, task);
  requireThat(SHA.test(checkpoint) && s.branch?.commit?.sha === checkpoint, 'post-push branch race');
  if (s.pr) {
    requireThat(s.pr.head.sha === checkpoint && (!plan.pr || s.pr.number === plan.pr), 'same PR/HEAD');
    validatePR({ ...s, pr: { ...s.pr, draft: false } }, task);
    requireThat(decisions(s, task).length === 0, 'terminal/already-reviewed published HEAD');
  }
  return true;
}

export async function publishAndDispatch(plan, load, candidate, io) {
  const validated = publicationPlan(plan, await load(), candidate);
  await io.commit(validated);
  publicationPlan(plan, await load(), candidate);
  await io.push(validated); // ordinary push: remote branch race must reject
  await io.recheckPublished(validated);
  const current = await io.pr(validated); // create draft once, or same correction PR
  await io.recheckPublished(validated, current);
  await io.ready(current);
  await io.recheckPublished(validated, current);
  await io.dispatch({ workflow: REVIEW_WORKFLOW, ref: 'main', inputs: { pr: current.number } });
  return current;
}
export async function dispatchPublishedCorrection(load, io) {
  const s = await load();
  const plan = correctionPlan(s); // requires uploaded receipt and successful actual source completion
  await io.dispatch({ workflow: IMPLEMENTATION_WORKFLOW, ref: 'main', inputs: { review_run: String(plan.source.runId) } });
  return plan;
}
