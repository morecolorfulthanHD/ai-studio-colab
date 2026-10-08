import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {
  taskStartPlan, correctionPlan, hash, publicationPlan, verificationReceipt, publishAndDispatch, publishedCheckpointGate,
} from '../../tools/ai-studio-orchestration/policy.mjs';
import { git, reconstruct, inspectDelta, verifyOffline, sanitizedEnvironment, checkedRun, parseTestSummary } from '../../tools/ai-studio-orchestration/controller.mjs';
import { fixture, reviewFixture } from './policy.test.mjs';
import { fixture as correctionFixture } from './correction-dispatch.test.mjs';

function candidate(plan) {
  const result = { status: 'VERIFICATION_PENDING', summary: 'proposed patch', changedPaths: [plan.task.paths[3]] };
  const patch = 'bounded fixture patch', tree = 'c'.repeat(40), context = { runId: 20, attempt: 1 };
  const checks = ['syntax', 'orchestration-tests'].map(name => ({ name, exitCode: 0, failed: 0, passed: 2, logHash: hash(name) }));
  return { result, patch, parent: plan.sha, tree, changes: [{ path: plan.task.paths[3], oldMode: '100644', newMode: '100644' }],
    ...context, verifier: { name: 'verify-implementation', conclusion: 'success', attempt: 1 },
    verification: verificationReceipt(plan, patch, result, tree, context, checks) };
}
test('publisher rejects altered, missing, failed and incomplete verification before mutation', () => {
  for (const mutate of [
    c => delete c.verification, c => c.verification.patchHash = hash('altered'),
    c => c.verification.resultHash = hash('altered'), c => c.verification.tree = 'd'.repeat(40),
    c => c.verification.checks.pop(), c => c.verification.checks[0].exitCode = 1,
    c => c.verification.checks[1].failed = 1, c => c.verification.checks[1].passed = 0,
    c => c.verifier.conclusion = 'failure', c => c.verifier.attempt = 2,
    c => c.result.status = 'ACCEPTED', c => c.result.status = 'CHECKPOINT',
    c => c.parent = 'd'.repeat(40), c => c.changes[0].newMode = '100755',
  ]) {
    const s = fixture(), plan = taskStartPlan(s), c = candidate(plan); mutate(c);
    assert.throws(() => publicationPlan(plan, s, c), /AUTHORITY_BLOCKED/);
  }
});
test('token-suppressed publication explicitly dispatches review only after pushed HEAD/PR readiness', async () => {
  const s = fixture(), plan = taskStartPlan(s), c = candidate(plan), calls = [];
  await publishAndDispatch(plan, async () => s, c, {
    recheckPublished: async () => {}, commit: async () => calls.push('commit'), push: async () => calls.push('push'),
    pr: async () => { calls.push('same-pr'); return { number: 12 }; },
    ready: async () => calls.push('ready'), dispatch: async d => { calls.push('dispatch'); assert.equal(d.inputs.pr, 12); },
  });
  assert.deepEqual(calls, ['commit', 'push', 'same-pr', 'ready', 'dispatch']);
});
test('revoked authority between commit and push publishes nothing', async () => {
  const s = fixture(), plan = taskStartPlan(s), c = candidate(plan); let pushed = false;
  await assert.rejects(publishAndDispatch(plan, async () => s, c, {
    commit: async () => { s.activation.liveAuthorized = false; }, push: async () => { pushed = true; },
  }));
  assert.equal(pushed, false);
});
test('verification environment strips secrets and executable Issue prose never runs', () => {
  const env = sanitizedEnvironment({ PATH: process.env.PATH, GH_TOKEN: 'fixture', OPENAI_API_KEY: 'fixture',
    NODE_OPTIONS: '--require evil', GIT_CONFIG_COUNT: '5', BASH_ENV: 'evil' });
  for (const key of ['GH_TOKEN', 'OPENAI_API_KEY', 'NODE_OPTIONS', 'GIT_CONFIG_COUNT', 'BASH_ENV']) assert.equal(env[key], undefined);
  assert.throws(() => checkedRun(process.execPath, ['-e', 'process.exit(7)'], process.cwd()), /verifier failed/);
});

const completeSummary = '# tests 3\n# pass 3\n# fail 0\n# cancelled 0\n# skipped 0\n# todo 0\n';
test('TAP summary accepts the complete positive total and all six counters', () => {
  assert.deepEqual(parseTestSummary('TAP version 13\n' + completeSummary + '# duration_ms 1\n'),
    { tests: 3, pass: 3, fail: 0, cancelled: 0, skipped: 0, todo: 0 });
  assert.deepEqual(parseTestSummary(completeSummary.replace(/\n/g, '\r\n')), parseTestSummary(completeSummary));
});
for (const field of ['tests', 'pass', 'fail', 'cancelled', 'skipped', 'todo']) {
  for (const [reason, change] of [
    ['missing', s => s.replace(new RegExp('^# ' + field + ' .*\\n', 'm'), '')],
    ['malformed', s => s.replace(new RegExp('^# ' + field + ' .*$', 'm'), '# ' + field + ' nope')],
    ['duplicate', s => s + '# ' + field + ' 0\n'],
    ['negative', s => s.replace(new RegExp('^# ' + field + ' .*$', 'm'), '# ' + field + ' -1')],
    ['unsafe', s => s.replace(new RegExp('^# ' + field + ' .*$', 'm'), '# ' + field + ' 9007199254740992')],
  ]) test('TAP summary rejects ' + reason + ' ' + field, () => {
    assert.throws(() => parseTestSummary(change(completeSummary)), /AUTHORITY_BLOCKED/);
  });
}
for (const [reason, log] of [
  ['empty', ''], ['malformed extra record', completeSummary + '# pass\t3\n'], ['spec reporter', completeSummary.replace(/# /g, 'ℹ ')],
  ['zero total', completeSummary.replace('# tests 3', '# tests 0').replace('# pass 3', '# pass 0')],
  ['total mismatch', completeSummary.replace('# tests 3', '# tests 4')],
  ['pass mismatch', completeSummary.replace('# pass 3', '# pass 2')],
  ...['fail', 'cancelled', 'skipped', 'todo'].map(key => [key, completeSummary.replace('# ' + key + ' 0', '# ' + key + ' 1')]),
]) test('TAP summary rejects ' + reason + ' before any receipt is created', () => {
  assert.throws(() => parseTestSummary(log), /AUTHORITY_BLOCKED/);
});

test('real bare Git: additive same-branch push, immutable parent, reconstruction and branch race rejection', () => {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'ai-studio-bare-'));
  try {
    const remote = path.join(temp, 'remote.git'), worker = path.join(temp, 'worker'), verifier = path.join(temp, 'verifier'), rival = path.join(temp, 'rival');
    git(temp, ['init', '--bare', remote]);
    git(temp, ['init', worker]);
    fs.mkdirSync(path.join(worker, 'tools/ai-studio-orchestration'), { recursive: true });
    for (const file of ['policy.mjs', 'controller.mjs']) fs.copyFileSync(new URL('../../tools/ai-studio-orchestration/' + file, import.meta.url), path.join(worker, 'tools/ai-studio-orchestration', file));
    fs.mkdirSync(path.join(worker, 'tests/ai-studio-orchestration'), { recursive: true });
    // Miniature actual subprocess fixtures; not substituted for this repository's required suite.
    for (const file of ['policy.test.mjs', 'publication.test.mjs', 'correction-dispatch.test.mjs'])
      fs.writeFileSync(path.join(worker, 'tests/ai-studio-orchestration', file), "import test from 'node:test'; import assert from 'node:assert/strict'; test('miniature',()=>assert.ok(true));\n");
    fs.mkdirSync(path.join(worker, 'docs'), { recursive: true });
    fs.writeFileSync(path.join(worker, 'docs/ai-studio-autonomous-wake-orchestration.md'), 'base\n');
    git(worker, ['add', '--all']); git(worker, ['commit', '-m', 'fixture base']);
    const base = git(worker, ['rev-parse', 'HEAD']).trim();
    git(worker, ['push', remote, 'HEAD:refs/heads/main']);
    git(temp, ['clone', '--branch', 'main', remote, verifier]);
    git(temp, ['clone', '--branch', 'main', remote, rival]);
    const s = fixture(); s.mainSha = base; s.baseCommit.sha = base;
    s.task.body = s.task.body.replace('a'.repeat(40), base);
    Object.values(s.grants)[0].body = Object.values(s.grants)[0].body.replace(hash(fixture().task.body), hash(s.task.body));
    const plan = taskStartPlan(s);
    fs.writeFileSync(path.join(worker, 'docs/ai-studio-autonomous-wake-orchestration.md'), 'bounded candidate\n');
    const delta = inspectDelta(worker, base), result = { status: 'VERIFICATION_PENDING', summary: 'fixture', changedPaths: delta.changes.map(c => c.path) };
    const context = { runId: 20, attempt: 1 };
    const actual = verifyOffline(verifier, plan, delta.patch, result, context);
    assert.equal(actual.tree, delta.tree); assert.equal(actual.receipt.checks[1].passed, 3); assert.match(actual.log, /# pass 3/); assert.match(actual.log, /# fail 0/);
    const c = { ...delta, result, parent: base, ...context, verification: actual.receipt,
      verifier: { name: 'verify-implementation', conclusion: 'success', attempt: 1 } };
    assert.equal(publicationPlan(plan, s, c).branch, plan.task.branch);
    const first = git(worker, ['commit-tree', delta.tree, '-p', base, '-m', 'additive one']).trim();
    git(worker, ['push', remote, first + ':refs/heads/' + plan.task.branch]);
    assert.equal(git(worker, ['rev-parse', first + '^']).trim(), base);
    assert.equal(git(worker, ['ls-remote', remote, 'refs/heads/' + plan.task.branch]).split(/\s/)[0], first);
    fs.writeFileSync(path.join(rival, 'docs/ai-studio-autonomous-wake-orchestration.md'), 'competing checkpoint\n');
    git(rival, ['add', '--all']); git(rival, ['commit', '-m', 'race from same parent']);
    assert.throws(() => git(rival, ['push', remote, 'HEAD:refs/heads/' + plan.task.branch]));
    assert.equal(git(worker, ['ls-remote', remote, 'refs/heads/' + plan.task.branch]).split(/\s/)[0], first);
    // Same PR metadata is carried into correction publication; no new task-start is permitted.
    const secondVerifier = path.join(temp, 'second-verifier');
    git(worker, ['checkout', '--detach', first]);
    git(temp, ['clone', '--branch', plan.task.branch, remote, secondVerifier]);
    fs.writeFileSync(path.join(worker, 'docs/ai-studio-autonomous-wake-orchestration.md'), 'bounded additive correction\n');
    const correctionDelta = inspectDelta(worker, first);
    const native = correctionFixture();
    native.mainSha = base; native.baseCommit = { sha: base, exists: true }; native.task = s.task;
    native.grants = s.grants; native.pr.head.sha = first; native.pr.body = native.pr.body.replace('a'.repeat(40), base);
    native.branch.commit.sha = first; native.lineage = { base, head: first, ancestor: true };
    native.changes = delta.changes;
    native.comments[0].body = native.comments[0].body.replace('b'.repeat(40), first);
    native.receipt.contractHash = hash(s.task.body); native.receipt.reviewedSha = first;
    native.receipt.controllerSha = base; native.receipt.commentBody = native.comments[0].body;
    native.receipt.commentHash = hash(native.receipt.commentBody);
    native.receipt.corrections[0].path = delta.changes[0].path;
    native.artifact.sha256 = hash(native.receipt); native.source.controllerSha = base;
    const correction = correctionPlan(native);
    assert.equal(correction.pr, 12); assert.equal(correction.task.branch, plan.task.branch);
    const correctionResult = { ...result, changedPaths: correctionDelta.changes.map(c => c.path) };
    const verifiedCorrection = verifyOffline(secondVerifier, correction, correctionDelta.patch, correctionResult, context);
    const correctionCandidate = { ...correctionDelta, result: correctionResult, parent: first, ...context,
      verification: verifiedCorrection.receipt, verifier: c.verifier };
    assert.equal(publicationPlan(correction, native, correctionCandidate).pr, 12);
    const second = git(worker, ['commit-tree', correctionDelta.tree, '-p', first, '-m', 'same-PR additive correction']).trim();
    git(worker, ['push', remote, second + ':refs/heads/' + plan.task.branch]);
    assert.equal(git(worker, ['rev-parse', second + '^']).trim(), first);
    git(worker, ['merge-base', '--is-ancestor', base, second]);
    assert.equal(git(worker, ['ls-remote', remote, 'refs/heads/' + plan.task.branch]).split(/\s/)[0], second);
    assert.throws(() => reconstruct(verifier, plan, delta.patch), /unclean/);
    // Actual Node subprocess failures or non-passing tests must never return a receipt.
    for (const [name, body] of [
      ['failed', "test('miniature',()=>assert.fail('fixture'));"],
      ['skipped', "test('miniature',{skip:true},()=>assert.ok(true));"],
      ['todo', "test('miniature',{todo:true},()=>assert.ok(true));"],
      ['cancelled', "test('miniature',{signal:AbortSignal.abort()},()=>assert.ok(true));"],
    ]) {
      const rejectedVerifier = path.join(temp, 'rejected-' + name);
      git(temp, ['clone', '--branch', 'main', remote, rejectedVerifier]);
      fs.writeFileSync(path.join(rejectedVerifier, 'tests/ai-studio-orchestration/policy.test.mjs'),
        "import test from 'node:test'; import assert from 'node:assert/strict'; " + body + '\n');
      git(rejectedVerifier, ['add', '--all']);
      git(rejectedVerifier, ['commit', '-m', 'negative verifier fixture']);
      const negativeBase = git(rejectedVerifier, ['rev-parse', 'HEAD']).trim();
      const negativePlan = { ...plan, sha: negativeBase };
      fs.writeFileSync(path.join(rejectedVerifier, 'docs/ai-studio-autonomous-wake-orchestration.md'), 'negative candidate\n');
      const negativeDelta = inspectDelta(rejectedVerifier, negativeBase);
      git(rejectedVerifier, ['reset', '--hard', negativeBase]);
      assert.throws(() => verifyOffline(rejectedVerifier, negativePlan, negativeDelta.patch, result, context),
        /AUTHORITY_BLOCKED/);
    }


  } finally { fs.rmSync(temp, { recursive: true, force: true }); }
});

test('published checkpoint guard rejects post-push authority and PR races before readiness/dispatch', () => {
  for (const mutate of [
    s => s.activation.liveAuthorized = false,
    s => s.task.body += '\nrevoked',
    s => s.branch.commit.sha = 'd'.repeat(40),
    s => s.pr.head.sha = 'd'.repeat(40),
    s => s.pr.number = 99,
  ]) {
    const s = fixture(), plan = taskStartPlan(s);
    plan.pr = 12;
    const r = reviewFixture();
    s.pr = r.pr; s.pr.head.sha = 'c'.repeat(40);
    s.branch = { commit: { sha: 'c'.repeat(40) } };
    s.lineage = { base: plan.sha, head: s.pr.head.sha, ancestor: true };
    assert.equal(publishedCheckpointGate(plan, s, 'c'.repeat(40)), true);
    mutate(s);
    assert.throws(() => publishedCheckpointGate(plan, s, 'c'.repeat(40)));
  }
});
test('post-push revocation prevents both PR readiness and explicit dispatch', async () => {
  const s = fixture(), plan = taskStartPlan(s), c = candidate(plan), calls = [];
  await assert.rejects(publishAndDispatch(plan, async () => s, c, {
    commit: async () => calls.push('commit'), push: async () => calls.push('push'),
    recheckPublished: async () => { throw Error('AUTHORITY_BLOCKED: revoked post-push'); },
    pr: async () => calls.push('pr'), ready: async () => calls.push('ready'), dispatch: async () => calls.push('dispatch'),
  }));
  assert.deepEqual(calls, ['commit', 'push']);
});
