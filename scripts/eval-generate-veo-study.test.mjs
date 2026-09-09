// Offline contracts only: mock HTTP responses, artificial bytes, and sleeper
// subprocesses. No API connection, paid submission, or detector/model call.
import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import { readFile, writeFile, mkdir, mkdtemp, rm, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn, spawnSync } from 'node:child_process';
import { GoogleGenAI, GenerateVideosOperation } from '@google/genai';
import { atomicJson, immutableJson, finalizeParent, hashFile, operationStatus,
  monitorDownload, verifySavedNegativeGate } from './eval-generate-veo-study.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const fixture = await mkdtemp(path.join(root, 'eval/runs/veo-offline-fixtures-'));
const planPath = path.join(root, 'eval/fixtures/shot-study-generation-plan.json');
const plan = JSON.parse(await readFile(planPath, 'utf8'));
const request = plan.veoRuns.find((r) => r.id === 'V1').request;
const operation = { name: 'models/veo-3.1-generate-preview/operations/offline-test-only', done: true,
  response: { generatedVideos: [{ video: { uri: 'https://generativelanguage.googleapis.com/v1beta/files/offline-test-only:download' } }] } };
const scriptPath = path.join(root, 'scripts/eval-generate-veo-study.mjs');
const checks = [];
function contract(name, fn) {
  test(name, { concurrency: false }, async () => {
    try { await fn(); checks.push({ name, status: 'passed' }); }
    catch (error) { checks.push({ name, status: 'failed', error: error.message }); throw error; }
  });
}
async function parentFixture(name) {
  const directory = path.join(fixture, name);
  await mkdir(directory);
  await writeFile(path.join(directory, 'video.mp4'), 'OFFLINE ARTIFICIAL BYTES: NOT A VIDEO OR EVALUATION PARENT');
  const context = { directory, rootDir: root, slot: 'V1', planSha: await hashFile(planPath),
    protocolSha: await hashFile(path.join(root, 'eval/AEGIS_SHOT_EVALUATION_PROTOCOL.md')),
    run: { request }, scriptSha: await hashFile(scriptPath), runtime: { offlineFixture: true } };
  const record = { schemaVersion: 1, status: 'download_validated', generationSlot: 'V1',
    generationPlanSha256: context.planSha, evaluationProtocolSha256: context.protocolSha,
    inputMedia: [], request, scriptSha256: context.scriptSha, runtime: context.runtime, operation };
  return { context, record };
}

contract('SDK serializes exact text-only request without using a network', async () => {
  const previous = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), method: init.method, body: init.body });
    return new Response(JSON.stringify({ name: operation.name, done: false }), { status: 200, headers: { 'content-type': 'application/json' } });
  };
  try {
    const ai = new GoogleGenAI({ apiKey: 'OFFLINE_FIXTURE_KEY', enterprise: false,
      httpOptions: { timeout: 30000, retryOptions: { attempts: 1 } } });
    const result = await ai.models.generateVideos(structuredClone(request));
    assert.equal(calls.length, 1);
    assert.equal(calls[0].method, 'POST');
    const body = JSON.parse(calls[0].body);
    assert.deepEqual(body.instances, [{ prompt: request.source.prompt }]);
    assert.equal(body.parameters.sampleCount, 1);
    assert.equal(body.parameters.durationSeconds, 8);
    assert.equal('seed' in body.parameters, false);
    assert.equal(body.parameters.resolution, '720p');
    assert.equal(body.parameters.aspectRatio, '16:9');
    const rehydrated = Object.assign(new GenerateVideosOperation(), JSON.parse(JSON.stringify(result)));
    const polled = await ai.operations.getVideosOperation({ operation: rehydrated });
    assert.equal(calls.length, 2);
    assert.equal(calls[1].method, 'GET');
    assert.equal(polled.name, operation.name);
  } finally { globalThis.fetch = previous; }
});

contract('SDK attempts1 cannot repeat a failed paid submission', async () => {
  const previous = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => { calls++; return new Response(JSON.stringify({ error: { code: 503, message: 'OFFLINE FAILURE' } }),
    { status: 503, headers: { 'content-type': 'application/json' } }); };
  try {
    const ai = new GoogleGenAI({ apiKey: 'OFFLINE_FIXTURE_KEY', enterprise: false,
      httpOptions: { timeout: 30000, retryOptions: { attempts: 1 } } });
    await assert.rejects(ai.models.generateVideos(structuredClone(request)));
    assert.equal(calls, 1);
  } finally { globalThis.fetch = previous; }
});

contract('unsupported caller seed fails before even the mock transport', async () => {
  const previous = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => { calls++; throw new Error('Transport should not be reached'); };
  try {
    const ai = new GoogleGenAI({ apiKey: 'OFFLINE_FIXTURE_KEY', enterprise: false });
    await assert.rejects(ai.models.generateVideos({ ...structuredClone(request), config: { ...request.config, seed: 123 } }), /seed parameter is only supported/);
    assert.equal(calls, 0);
  } finally { globalThis.fetch = previous; }
});

contract('terminal failure, filtering, invalid output, and uncertainty stay distinct', async () => {
  assert.equal(operationStatus(operation), 'generated');
  assert.equal(operationStatus({ name: operation.name, done: false }), 'running');
  assert.equal(operationStatus({ done: false }), 'submission_failed_or_uncertain');
  assert.equal(operationStatus({ ...operation, error: { code: 13 } }), 'generation_failed');
  assert.equal(operationStatus({ ...operation, response: { raiMediaFilteredCount: 1 } }), 'generation_filtered');
  assert.equal(operationStatus({ ...operation, response: { generatedVideos: [] } }), 'generation_invalid_response');
  assert.equal(operationStatus({ ...operation, done: 'true' }), 'generation_invalid_response');
});

contract('mutable state is complete JSON and immutable records refuse replacement', async () => {
  const mutable = path.join(fixture, 'state-test.json');
  await atomicJson(mutable, { n: 1 }); await atomicJson(mutable, { n: 2 });
  assert.deepEqual(JSON.parse(await readFile(mutable, 'utf8')), { n: 2 });
  const immutable = path.join(fixture, 'immutable-test.json');
  await immutableJson(immutable, { n: 1 });
  const original = await hashFile(immutable);
  await assert.rejects(immutableJson(immutable, { n: 2 }), { code: 'EEXIST' });
  assert.equal(await hashFile(immutable), original);
});

contract('wrapper finalization is idempotent and never changes the raw receipt', async () => {
  const { context, record } = await parentFixture('idempotent');
  await finalizeParent(context, record);
  const receipt = path.join(context.directory, 'receipt.json');
  const before = await hashFile(receipt);
  await finalizeParent(context);
  assert.equal(await hashFile(receipt), before);
  const wrapper = JSON.parse(await readFile(path.join(context.directory, 'parent-receipt.json'), 'utf8'));
  assert.equal(wrapper.rawGenerationReceipt.sha256, before);
  assert.equal(wrapper.modelRevision, 'provider-managed-unpinned');
});

contract('failed wrapper creation resumes locally with the original raw hash', async () => {
  const { context, record } = await parentFixture('wrapper-recovery');
  const wrapper = path.join(context.directory, 'parent-receipt.json');
  await mkdir(wrapper);
  await assert.rejects(finalizeParent(context, record));
  const before = await hashFile(path.join(context.directory, 'receipt.json'));
  await rm(wrapper, { recursive: true });
  await finalizeParent(context);
  assert.equal(await hashFile(path.join(context.directory, 'receipt.json')), before);
  assert.equal((await stat(wrapper)).isFile(), true);
});

contract('changed completed media and source identity are rejected', async () => {
  const { context, record } = await parentFixture('changed-source');
  await finalizeParent(context, record);
  await assert.rejects(finalizeParent({ ...context, slot: 'V2' }));
  await writeFile(path.join(context.directory, 'video.mp4'), 'ALTERED OFFLINE BYTES');
  await assert.rejects(finalizeParent(context), /bytes changed/);
});

contract('actual builder accepts matching schema and rejects an edited raw receipt', async () => {
  const { context, record } = await parentFixture('builder-schema');
  const copiedPlan = structuredClone(plan); copiedPlan.veoScriptSha256 = context.scriptSha;
  const fixturePlan = path.join(context.directory, 'offline-plan-copy.json');
  await writeFile(fixturePlan, JSON.stringify(copiedPlan));
  context.planSha = await hashFile(fixturePlan); record.generationPlanSha256 = context.planSha;
  await finalizeParent(context, record);
  const wrapper = path.join(context.directory, 'parent-receipt.json');
  const code = 'import importlib.util,sys; from pathlib import Path; s=importlib.util.spec_from_file_location("builder",sys.argv[1]); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); m.GENERATION_PLAN=Path(sys.argv[5]); m.parent_record("V1",{"generationSlot":"V1"},{"V1":Path(sys.argv[2])},sys.argv[3],sys.argv[4])';
  const args = ['-c', code, path.join(root, 'scripts/build-shot-study.py'), wrapper, context.planSha, context.protocolSha, fixturePlan];
  const accepted = spawnSync(path.join(root, 'eval/.venv/bin/python'), args, { encoding: 'utf8', timeout: 15000 });
  assert.equal(accepted.status, 0, accepted.stderr);
  const receiptPath = path.join(context.directory, 'receipt.json');
  const changed = JSON.parse(await readFile(receiptPath, 'utf8')); changed.request = {};
  await writeFile(receiptPath, JSON.stringify(changed));
  assert.notEqual(spawnSync(path.join(root, 'eval/.venv/bin/python'), args, { encoding: 'utf8', timeout: 15000 }).status, 0);
});

contract('a fabricated passing gate summary cannot authorize generation', async () => {
  const fake = path.join(fixture, 'fabricated-gate.json');
  await writeFile(fake, JSON.stringify({ stage: 'negative-45', status: 'passed', recipeFingerprint: '0'.repeat(64),
    configuration: { modelSha256: 'wrong-model' }, selected: 45, completed: 45, errors: 0, incorrect: 0,
    frozenSnapshotAndWeightsUnchanged: true, workingRunnerUnchanged: true }));
  await assert.rejects(verifySavedNegativeGate(fake), /saved-evidence validation/);
});

contract('download watchdog terminates a stalled child', async () => {
  const child = spawn(process.execPath, ['-e', 'setTimeout(()=>{},10000)'], { stdio: ['ignore', 'ignore', 'pipe'] });
  await assert.rejects(monitorDownload(child, path.join(fixture, 'absent.part'), { timeoutMs: 150 }), /wall-time/);
  assert.ok(child.signalCode || child.exitCode !== null);
});

contract('download watchdog terminates an oversized child output', async () => {
  const output = path.join(fixture, 'oversize.part');
  const child = spawn(process.execPath, ['-e', 'require("node:fs").writeFileSync(process.argv[1],Buffer.alloc(2000));setTimeout(()=>{},10000)', output],
    { stdio: ['ignore', 'ignore', 'pipe'] });
  await assert.rejects(monitorDownload(child, output, { timeoutMs: 2000, maxBytes: 1000 }), /byte limit/);
});

after(async () => {
  const receipt = { status: checks.length === 12 && checks.every((c) => c.status === 'passed') ? 'passed' : 'failed',
    testCount: checks.length, networkConnections: 0, apiSubmissions: 0, modelCalls: 0,
    fixtures: 'Artificial bytes and mocked fetch responses only; temporary fixtures removed.',
    node: process.version, scriptSha256: await hashFile(scriptPath),
    contractFile: 'scripts/eval-generate-veo-study.test.mjs',
    contractSha256: await hashFile(fileURLToPath(import.meta.url)), checks };
  await writeFile(path.join(root, 'eval/sources/veo-offline-contract-receipt.json'), JSON.stringify(receipt, null, 2) + '\n');
  await rm(fixture, { recursive: true });
});
