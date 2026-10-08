import test from 'node:test';
import assert from 'node:assert/strict';
import {
  REPOSITORY, REVIEW_WORKFLOW, hash, correctionPlan, dispatchPublishedCorrection, taskContract,
} from '../../tools/ai-studio-orchestration/policy.mjs';
import { reviewFixture } from './policy.test.mjs';

export function fixture() {
  const s = reviewFixture(), task = taskContract(s.task);
  const body = 'AI_STUDIO_DECISION: CHANGES_REQUESTED\nREVIEWED_SHA: ' + s.pr.head.sha +
    '\nAI_STUDIO_TASK_ID: ' + task.taskId + '\n\nCorrect only the authorized file.';
  s.comments = [{ id: 40, body, user: { id: 41898282, login: 'github-actions[bot]' }, performed_via_github_app: { slug: 'github-actions' } }];
  s.receipt = { version: 1, repository: REPOSITORY, taskId: task.taskId, contractHash: task.contractHash,
    reviewedSha: s.pr.head.sha, pr: s.pr.number, runId: 30, attempt: 1, controllerSha: s.mainSha,
    commentId: 40, commentBody: body, commentHash: hash(body), createdAt: '2026-10-06T23:00:00Z', expiresAt: '2026-10-08T00:00:00Z',
    corrections: [{ path: task.paths[3], requirement: 'Correct guard and add rejection fixture.', verification: 'orchestration' }] };
  s.source = { id: 30, attempt: 1, repository: REPOSITORY, path: REVIEW_WORKFLOW, status: 'completed', conclusion: 'success',
    headRepository: REPOSITORY, headSha: s.pr.head.sha, controllerSha: s.mainSha, workflowHash: hash(s.files[REVIEW_WORKFLOW]),
    actor: 'github-actions[bot]', event: 'workflow_dispatch',
    jobs: ['gate', 'reviewer', 'publish-review'].map(name => ({ name, attempt: 1, conclusion: 'success' })) };
  s.artifact = { name: 'ai-studio-review-receipt', runId: 30, attempt: 1, expired: false, sha256: hash(s.receipt) };
  return s;
}
test('authenticated completed review plans one additive correction on same PR and branch', () => {
  const s = fixture(), p = correctionPlan(s);
  assert.equal(p.pr, 12); assert.equal(p.sha, s.pr.head.sha); assert.equal(p.task.branch, 'codex/fixture-task-v1');
  assert.deepEqual(p.source, { runId: 30, attempt: 1, commentId: 40 });
});
for (const [name, mutate] of [
  ['missing receipt', s => delete s.receipt],
  ['altered receipt', s => s.receipt.commentId = 41],
  ['expired artifact', s => s.artifact.expired = true],
  ['foreign artifact run', s => s.artifact.runId = 31],
  ['wrong receipt attempt', s => s.artifact.attempt = 2],
  ['missing immutable digest', s => delete s.artifact.sha256],
  ['failed source', s => s.source.conclusion = 'failure'],
  ['unfinished source', s => s.source.status = 'in_progress'],
  ['foreign source repository', s => s.source.repository = 'foreign/repo'],
  ['foreign source workflow', s => s.source.path = '.github/workflows/fake.yml'],
  ['altered source workflow definition', s => s.source.workflowHash = hash('fake')],
  ['foreign head repository', s => s.source.headRepository = 'foreign/repo'],
  ['wrong source controller', s => s.source.controllerSha = 'c'.repeat(40)],
  ['failed reviewer job', s => s.source.jobs[1].conclusion = 'failure'],
  ['missing publisher job', s => s.source.jobs.pop()],
  ['rerun mismatch', s => s.source.jobs[1].attempt = 2],
  ['wrong App', s => s.comments[0].performed_via_github_app.slug = 'other'],
  ['spoofed username', s => s.comments[0].user.id = 1],
  ['Work comment is not native receipt', s => s.comments[0].user.id = 35986152],
  ['copied decision body', s => s.comments[0].body += '\ncopy'],
  ['stale HEAD', s => s.pr.head.sha = 'c'.repeat(40)],
  ['changed contract', s => s.task.body += '\nchanged'],
  ['duplicate correction', s => s.processed = [40]],
  ['correction bound', s => s.correctionCount = 1],
  ['out-of-scope correction', s => { s.receipt.corrections[0].path = 'AGENTS.md'; s.artifact.sha256 = hash(s.receipt); }],
  ['expired receipt', s => { s.receipt.expiresAt = '2026-10-06T00:00:00Z'; s.artifact.sha256 = hash(s.receipt); }],
  ['revoked activation', s => s.activation.liveAuthorized = false],
]) test('native correction rejects ' + name, async () => {
  const s = fixture(); mutate(s); let dispatched = false;
  await assert.rejects(dispatchPublishedCorrection(async () => s, { dispatch: async () => { dispatched = true; } }));
  assert.equal(dispatched, false);
});
for (const decision of ['ACCEPTED', 'HUMAN_REQUIRED']) test(decision + ' is terminal and never dispatches', async () => {
  const s = fixture(); s.comments[0].body = s.comments[0].body.replace('CHANGES_REQUESTED', decision);
  s.receipt.commentBody = s.comments[0].body; s.receipt.commentHash = hash(s.comments[0].body); s.artifact.sha256 = hash(s.receipt);
  let calls = 0;
  await assert.rejects(dispatchPublishedCorrection(async () => s, { dispatch: async () => { calls++; } }));
  assert.equal(calls, 0);
});
test('explicit token-suppressed correction dispatch follows real upload and successful completion; fallback deduplicates', async () => {
  const s = fixture(), ordering = [];
  s.artifact = null;
  await assert.rejects(dispatchPublishedCorrection(async () => s, { dispatch: async () => ordering.push('early') }));
  s.artifact = fixture().artifact; ordering.push('receipt-uploaded'); s.source.status = 'in_progress';
  await assert.rejects(dispatchPublishedCorrection(async () => s, { dispatch: async () => ordering.push('early') }));
  s.source.status = 'completed'; ordering.push('source-completed');
  await dispatchPublishedCorrection(async () => s, { dispatch: async d => {
    ordering.push('dispatch'); assert.equal(d.ref, 'main'); assert.deepEqual(d.inputs, { review_run: '30' });
  } });
  s.processed = [40];
  await assert.rejects(dispatchPublishedCorrection(async () => s, { dispatch: async () => ordering.push('duplicate') }));
  assert.deepEqual(ordering, ['receipt-uploaded', 'source-completed', 'dispatch']);
});
