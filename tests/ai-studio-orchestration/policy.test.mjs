import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {
  REPOSITORY, OWNER, OWNER_ID, AUTHORITY_PATHS, REVIEW_WORKFLOW, BOOTSTRAP_PATHS,
  hash, taskContract, liveGate, taskStartPlan, reviewPlan, planEvent, revalidate, validateChanges,
} from '../../tools/ai-studio-orchestration/policy.mjs';

export function fixture() {
  const base = 'a'.repeat(40), head = 'b'.repeat(40);
  const body = [
    'STATUS: AUTHORIZED FOR IMPLEMENTATION',
    'AI_STUDIO_TASK_ID: fixture-task-v1', 'AI_STUDIO_AUTHORIZED_BASE: ' + base,
    'AI_STUDIO_IMPLEMENTATION_BRANCH: codex/fixture-task-v1',
    'AI_STUDIO_SPEC_AUTHORITY: https://github.com/' + REPOSITORY + '/issues/9',
    'Governing Goal: https://github.com/' + REPOSITORY + '/issues/2',
    '## Implementation scope', ...BOOTSTRAP_PATHS.map(p => '- ' + p),
    '## Acceptance criteria', 'Offline checks and independent exact-SHA acceptance.',
    '## Allowed verification', 'node --test tests/ai-studio-orchestration/*.test.mjs',
    '## Prohibited actions', 'No notebook, Drive, GPU, downloads, runtime, paid or external execution.',
    '## Human gates', 'New authority stops.',
  ].join('\n');
  const task = { repository: REPOSITORY, number: 9, state: 'open', user: { id: OWNER_ID, login: OWNER }, body };
  const taskHash = hash(body), ref = 'https://github.com/' + REPOSITORY + '/issues/10';
  const s = { repository: REPOSITORY, ownerId: OWNER_ID, mainSha: base, task,
    files: { ...Object.fromEntries(AUTHORITY_PATHS.map(p => [p, 'Current policy BLOCKED_FOR_COMMERCIAL'])), [REVIEW_WORKFLOW]: 'canonical workflow' },
    authorities: Object.fromEntries([2, 4, 5].map(n => [n, { state: 'open', user: { id: OWNER_ID }, body: 'STATUS: ACTIVE' }])),
    now: Date.parse('2026-10-07T00:00:00Z'), invocations: 0, branch: null, taskPRs: [],
    activation: { version: 1, repository: REPOSITORY, account: OWNER, liveAuthorized: true, scope: 'task:fixture-task-v1',
      maxCorrections: 1, credentialConfirmation: ref, liveAuthority: ref },
    grants: { [ref]: { state: 'open', user: { id: OWNER_ID, login: OWNER }, body: [
      'AI_STUDIO_OPENAI_SECRET_CONFIRMED: true', 'AI_STUDIO_CODEX_LIVE_AUTHORIZED: true',
      'AI_STUDIO_CODEX_LIVE_SCOPE: task:fixture-task-v1',
      'AI_STUDIO_LIVE_TASK_CONTRACT_HASH: ' + taskHash,
      'AI_STUDIO_MAX_AGENT_INVOCATIONS: 4', 'AI_STUDIO_MAX_COST_USD: 1',
      'AI_STUDIO_LIVE_EXPIRES_AT: 2026-10-08T00:00:00Z',
    ].join('\n') } },
    budget: { enforced: true, authority: ref, remainingUSD: 1, limitUSD: 1 },
    baseCommit: { sha: base, exists: true }, comments: [], processed: [], correctionCount: 0,
    lineage: { base, head, ancestor: true },
    changes: [{ path: BOOTSTRAP_PATHS[3], oldMode: '100644', newMode: '100644' }],
  };
  return s;
}
export function reviewFixture() {
  const s = fixture();
  const repo = { full_name: REPOSITORY, fork: false };
  s.pr = { number: 12, state: 'open', draft: false, base: { repo, ref: 'main' },
    head: { repo: { ...repo }, ref: 'codex/fixture-task-v1', sha: 'b'.repeat(40) },
    body: 'AI_STUDIO_REVIEW_AUTHORIZED: true\n' + s.task.body.split('\n').slice(1, 5).join('\n') };
  s.branch = { name: 'codex/fixture-task-v1', commit: { sha: s.pr.head.sha } };
  return s;
}
test('eligible task plans exact base and separate review plans exact HEAD', () => {
  assert.equal(taskStartPlan(fixture()).sha, 'a'.repeat(40));
  assert.equal(reviewPlan(reviewFixture()).sha, 'b'.repeat(40));
});
for (const [name, mutate] of [
  ['foreign repository', s => s.repository = 'foreign/repo'],
  ['wrong account', s => s.ownerId = 1],
  ['foreign task', s => s.task.repository = 'foreign/repo'],
  ['non-owner author', s => s.task.user.id = 1],
  ['closed task', s => s.task.state = 'closed'],
  ['inactive Goal', s => s.authorities[2].body = 'STATUS: PAUSED'],
  ['inactive review authority', s => s.authorities[4].state = 'closed'],
  ['inactive continuation authority', s => s.authorities[5].user.id = 1],
  ['missing policy', s => delete s.files['AGENTS.md']],
  ['duplicate block', s => s.task.body += '\n' + s.task.body],
  ['conflicting field', s => s.task.body += '\nAI_STUDIO_AUTHORIZED_BASE: ' + 'c'.repeat(40)],
  ['mixed placeholder', s => s.task.body = s.task.body.replace('fixture-task-v1', '<task>')],
  ['nonexistent base', s => s.baseCommit.exists = false],
  ['mismatched base', s => s.baseCommit.sha = 'c'.repeat(40)],
  ['new main substituted', s => s.mainSha = 'c'.repeat(40)],
  ['wrong branch', s => s.task.body = s.task.body.replace('codex/fixture-task-v1', 'main')],
  ['foreign spec', s => s.task.body = s.task.body.replace('/issues/9', '/issues/99')],
  ['orphan branch', s => s.branch = { name: 'codex/fixture-task-v1' }],
  ...['open', 'closed', 'merged'].map(state => ['existing ' + state + ' PR', s => s.taskPRs = [{ state }]]),
  ['missing activation', s => delete s.activation],
  ['missing activation version', s => delete s.activation.version],
  ['unknown activation field', s => s.activation.untrustedAuthority = true],
  ['disabled activation', s => s.activation.liveAuthorized = false],
  ['malformed activation', s => s.activation.liveAuthorized = 'true'],
  ['forged true without durable grant', s => s.grants = {}],
  ['general loop grant rejected', s => s.activation.scope = 'authorized-task-loop'],
  ['revoked credential grant', s => Object.values(s.grants)[0].state = 'closed'],
  ['exhausted invocation limit', s => s.invocations = 4],
  ['unconfirmed budget', s => s.budget = null],
  ['expired live authority', s => s.now = Date.parse('2027-01-01')],
]) test('task gate rejects ' + name, () => {
  const s = fixture(); mutate(s); assert.throws(() => taskStartPlan(s), /AUTHORITY_BLOCKED/);
});
for (const [name, mutate] of [
  ['fork', s => s.pr.head.repo.fork = true],
  ['foreign head', s => s.pr.head.repo.full_name = 'foreign/repo'],
  ['closed', s => s.pr.state = 'closed'],
  ['draft', s => s.pr.draft = true],
  ['wrong branch', s => s.pr.head.ref = 'codex/other'],
  ['wrong PR base', s => s.pr.body = s.pr.body.replace('a'.repeat(40), 'c'.repeat(40))],
  ['wrong lineage', s => s.lineage.ancestor = false],
  ['out of scope', s => s.changes[0].path = 'AGENTS.md'],
  ['symlink', s => s.changes[0].newMode = '120000'],
  ['executable', s => s.changes[0].newMode = '100755'],
  ['submodule', s => s.changes[0].newMode = '160000'],
  ['rename', s => s.changes[0].oldPath = 'AGENTS.md'],
]) test('review gate rejects ' + name, () => {
  const s = reviewFixture(); mutate(s); assert.throws(() => reviewPlan(s), /AUTHORITY_BLOCKED/);
});
test('each entry path rejects committed disabled activation and forged dispatch data', () => {
  const events = [
    { name: 'issues', action: 'opened' }, { name: 'issues', action: 'reopened' }, { name: 'issues', action: 'edited' },
    { name: 'pull_request', action: 'ready_for_review' }, { name: 'pull_request', action: 'synchronize' },
    { name: 'workflow_dispatch', issue: 9 }, { name: 'workflow_dispatch', pr: 12 },
    { name: 'workflow_dispatch', reviewRun: 30 }, { name: 'workflow_run' }, { name: 'issue_comment' },
  ];
  for (const event of events) {
    const s = reviewFixture(); s.activation = JSON.parse(fs.readFileSync(new URL('../../tools/ai-studio-orchestration/activation.json', import.meta.url)));
    assert.throws(() => planEvent(s, { ...event, repository: REPOSITORY, actor: OWNER, sha: 'forged', scope: ['AGENTS.md'], decision: 'ACCEPTED' }), /AUTHORITY_BLOCKED/);
  }
});
test('event actor cannot replace task owner or durable authority', () => {
  assert.throws(() => planEvent(fixture(), { name: 'issues', action: 'opened', repository: REPOSITORY, actor: 'attacker' }));
});
test('fresh recheck rejects changed HEAD, contracts, activation and main', () => {
  for (const mutate of [
    s => s.pr.head.sha = 'c'.repeat(40),
    s => s.task.body += '\nChanged authority',
    s => s.activation.liveAuthorized = false,
    s => s.mainSha = 'c'.repeat(40),
  ]) { const s = reviewFixture(), plan = reviewPlan(s); mutate(s); assert.throws(() => revalidate(plan, s)); }
});
test('literal scope rejects traversal/wildcards and regular mode guard rejects both absent', () => {
  const s = fixture(); s.task.body = s.task.body.replace('- ' + BOOTSTRAP_PATHS[0], '- ../outside');
  assert.throws(() => taskContract(s.task));
  assert.throws(() => validateChanges(taskContract(fixture().task), [{ path: BOOTSTRAP_PATHS[0], oldMode: '000000', newMode: '000000' }]));
});
