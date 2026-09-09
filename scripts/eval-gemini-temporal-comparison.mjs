#!/usr/bin/env node
// Fixed, single-use Gemini comparison. No current application imports or rebuild.
import { createHash } from 'node:crypto';
import { readFile, writeFile, mkdir, copyFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { resolve, relative } from 'node:path';
import { pathToFileURL } from 'node:url';

const ROOT = process.cwd();
const OUTPUT = resolve(ROOT, 'eval/runs/sightengine-temporal-screen-v2-gemini-comparison');
const MANIFEST = 'eval/fixtures/sightengine-temporal-screen-v2.json';
const MANIFEST_SHA = '1374a18b17699d6aef0ef0868b21f9f580bdbaa667f26caa45d92d0dcacc25b7';
const PRIOR = 'eval/runs/user-reel-Da7nZ5hs6H7-gemini-v1';
const ADAPTER_SHA = '81656b5662ce2d9089670580527980e7e1a8d9d04e9aa8b2611e6b0d3e7ab7b3';
const FINGERPRINT = 'e5924b9a24e01b6da7c2a09667f9122a7e8bc4bf42d097212e3bac40f74c352f';
const VERSION = 'evidence-2.8:e5924b9a24e01b6da7c2a096';
const MODEL = 'gemini-3.7-flash';
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const now = () => new Date().toISOString();
let secrets = [];
function safeJson(value) {
  let text = JSON.stringify(value, null, 2);
  for (const secret of secrets) if (secret) text = text.replaceAll(secret, '[REDACTED]');
  return text + '\n';
}
async function save(path, value) {
  await writeFile(resolve(OUTPUT, path), safeJson(value), { flag: 'wx' });
}
function assert(ok, reason) { if (!ok) throw new Error(reason); }
function validateResult(result, item) {
  assert(result.detectorFingerprint === FINGERPRINT, 'IdentityMismatch: detector fingerprint');
  assert(result.analyzerVersion === VERSION, 'IdentityMismatch: analyzer version');
  assert(result.model === MODEL, 'IdentityMismatch: model');
  assert(result.videoProcessing === 'agentic', 'IdentityMismatch: review mode');
  assert(result.mediaReceipt?.sha256 === item.sha256, 'IdentityMismatch: media hash');
  assert(result.source?.platformVideoId === item.sha256, 'IdentityMismatch: source hash');
  assert(result.cacheHit === false, 'IdentityMismatch: cache');
  const passes = result.videoAnalysis?.inspection?.passes;
  assert(Array.isArray(passes) && passes.length >= 2, 'IdentityMismatch: missing pass receipts');
  assert(passes.every(pass => pass.model === MODEL), 'IdentityMismatch: pass model');
  assert(passes.some(pass => pass.kind === 'sweep' && pass.mode === 'static' && pass.fps === 2), 'IdentityMismatch: sweep configuration');
  assert(passes.some(pass => pass.kind === 'review' && pass.mode === 'agentic' && pass.fps === null), 'IdentityMismatch: review configuration');
  assert(['ai', 'not_ai', 'abstain'].includes(result.decision), 'IdentityMismatch: decision schema');
  return {
    inputTokensObserved: passes.reduce((sum, pass) => sum + (Number.isFinite(pass.inputTokens) ? pass.inputTokens : 0), 0),
    outputTokensObserved: passes.reduce((sum, pass) => sum + (Number.isFinite(pass.outputTokens) ? pass.outputTokens : 0), 0),
    passes: passes.map(({ kind, status, model, elapsedMs, inputTokens, outputTokens, validForCorroboration }) =>
      ({ kind, status, model, elapsedMs, inputTokens, outputTokens, validForCorroboration })),
    missingUsagePasses: passes.filter(pass => !Number.isFinite(pass.inputTokens) || !Number.isFinite(pass.outputTokens)).length,
    failedPasses: passes.filter(pass => pass.status !== 'complete').length,
    usageMeaning: 'Sum of returned pass receipts; internal retries and failed requests may incur unreported usage. Not billing reconciliation.',
  };
}
function safeError(error) {
  const message = String(error?.message ?? 'Unknown operational error');
  // Stable categories only: never save raw provider error text or request objects.
  const category = message.startsWith('IdentityMismatch:') ? message :
    /quota|429|rate.limit/i.test(message) ? 'ProviderRateLimit' :
    /401|403|permission|api.key|unauthorized|authentication/i.test(message) ? 'ProviderAuthentication' :
    /timeout|timed.out|abort/i.test(message) ? 'OperationalTimeout' :
    /schema|json|parse|invalid/i.test(message) ? 'ResponseValidationError' :
    /upload|processing|file/i.test(message) ? 'MediaProcessingError' : 'UnclassifiedOperationalError';
  return { category, rawErrorOmitted: true };
}

async function main() {
  const manifestBytes = await readFile(resolve(ROOT, MANIFEST));
  assert(hash(manifestBytes) === MANIFEST_SHA, 'Frozen manifest mismatch');
  const manifest = JSON.parse(manifestBytes);
  assert(manifest.cases.length === 25 && new Set(manifest.cases.map(row => row.sha256)).size === 25, 'Fixed cohort mismatch');
  const oldReceiptBytes = await readFile(resolve(ROOT, PRIOR, 'receipt.json'));
  const oldReceipt = JSON.parse(oldReceiptBytes);
  const adapterBytes = await readFile(resolve(ROOT, PRIOR, 'adapter.mjs'));
  assert(hash(adapterBytes) === ADAPTER_SHA && oldReceipt.bundleSha256 === ADAPTER_SHA, 'Preserved adapter mismatch');
  assert(oldReceipt.result?.detectorFingerprint === FINGERPRINT && oldReceipt.result?.model === MODEL, 'Original detector receipt mismatch');
  for (const item of manifest.cases) {
    const path = resolve(ROOT, item.path);
    assert(path.startsWith(ROOT + '/eval/media/') || path.startsWith(ROOT + '/eval/runs/aegis-shots-v1-negative-build/media/'), 'Media outside fixed evaluation media directories');
    const bytes = await readFile(path);
    assert(bytes.length === item.media.bytes && hash(bytes) === item.sha256, 'Media bytes mismatch: ' + item.id);
  }
  // Verify the old bundle source snapshot, never the changing application sources.
  for (const file of oldReceipt.source) {
    const path = resolve(ROOT, PRIOR, 'source', file.path);
    assert(path.startsWith(resolve(ROOT, PRIOR, 'source') + '/'), 'Snapshot traversal');
    assert(hash(await readFile(path)) === file.sha256, 'Original source snapshot mismatch: ' + file.path);
  }
  const nextRequire = createRequire(import.meta.resolve('next/package.json'));
  nextRequire('@next/env').loadEnvConfig(ROOT, false, { info() {}, error() {} });
  secrets = [process.env.GEMINI_API_KEY, process.env.GOOGLE_API_KEY, process.env.SIGHTENGINE_API_USER, process.env.SIGHTENGINE_API_SECRET,
    process.env.SUPABASE_SECRET_KEY, process.env.SUPABASE_SERVICE_ROLE_KEY, process.env.YOUTUBE_API_KEY];
  assert(Boolean(process.env.GEMINI_API_KEY || process.env.GOOGLE_API_KEY), 'Gemini credential missing');
  // Explicit parent-authorized model pins; no retry, prompt, score, or sampling change.
  process.env.GEMINI_MODEL = MODEL;
  process.env.GEMINI_REVIEW_MODEL = MODEL;
  assert((process.env.GEMINI_VIDEO_PROCESSING?.trim() || 'agentic') === 'agentic', 'Review mode environment mismatch');
  assert(Number(process.env.GEMINI_SWEEP_FPS || 2) === 2 && Number(process.env.GEMINI_REVIEW_FPS || 6) === 6, 'Sampling environment mismatch');
  const plan = {
    schemaVersion: 1, kind: 'fixed-exact-byte-gemini-comparison', startedAt: now(),
    manifest: { path: MANIFEST, sha256: MANIFEST_SHA }, cases: 25, concurrency: 2, outerRetries: 0,
    expected: { detectorFingerprint: FINGERPRINT, analyzerVersion: VERSION, model: MODEL },
    adapter: { originalPath: `${PRIOR}/adapter.mjs`, sha256: ADAPTER_SHA, export: 'analyzeEvaluationVideo' },
    originalReceipt: { path: `${PRIOR}/receipt.json`, sha256: hash(oldReceiptBytes) }, originalSource: oldReceipt.source,
    runner: { path: relative(ROOT, import.meta.filename), sha256: hash(await readFile(import.meta.filename)) },
    runtime: { node: process.version, sdkPackageSha256: hash(await readFile(resolve(ROOT, 'node_modules/@google/genai/package.json'))) },
    applicationRetryPolicyPreserved: true, labelsSentToModel: false, neutralFilename: 'video-under-review.mp4',
    stoppingRule: 'No new starts after three identical top-level operational error categories; identity mismatch stops immediately. Inflight calls finish.',
    purpose: 'Paired development comparison after failed Sightengine screen; not independent validation or a calibrated accuracy claim.',
  };
  if (process.argv.includes('--preflight-only')) {
    console.log(JSON.stringify({ status: 'preflight_passed', cases: 25, adapterSha256: ADAPTER_SHA, manifestSha256: MANIFEST_SHA, model: MODEL, noModelCalls: true }));
    return;
  }
  assert(process.argv.length === 2, 'Unsupported arguments');
  await mkdir(OUTPUT); // Exclusive output claim: this runner cannot resume or repeat.
  await save('execution.json', plan);
  await writeFile(resolve(OUTPUT, 'manifest.json'), manifestBytes, { flag: 'wx' });
  await writeFile(resolve(OUTPUT, 'adapter.mjs'), adapterBytes, { flag: 'wx' });
  await copyFile(import.meta.filename, resolve(OUTPUT, 'runner.mjs'));
  await writeFile(resolve(OUTPUT, 'original-receipt.json'), oldReceiptBytes, { flag: 'wx' });
  const adapter = await import(pathToFileURL(resolve(OUTPUT, 'adapter.mjs')).href);
  assert(typeof adapter.analyzeEvaluationVideo === 'function', 'Missing adapter export');
  const started = Date.now();
  let nextIndex = 0, stopReason = null, completed = 0;
  const results = new Array(25), errorCounts = new Map();
  async function worker() {
    while (!stopReason && nextIndex < manifest.cases.length) {
      const index = nextIndex++, item = manifest.cases[index], caseStarted = Date.now();
      const prefix = `${String(index + 1).padStart(2, '0')}-${item.id}`;
      const base = { index, id: item.id, mediaSha256: item.sha256, startedAt: now() };
      await save(`${prefix}.intent.json`, { ...base, adapterSha256: ADAPTER_SHA, manifestSha256: MANIFEST_SHA, outgoingFields: ['path', 'mimeType'] });
      let row;
      try {
        // Reverify immediately before invocation. Adapter only receives neutral path/type.
        assert(hash(await readFile(resolve(ROOT, item.path))) === item.sha256, 'IdentityMismatch: pre-invocation bytes');
        const result = await adapter.analyzeEvaluationVideo({ path: resolve(ROOT, item.path), mimeType: 'video/mp4' });
        // Retain even an identity-invalid result for the audit, without counting it as compatible.
        row = { ...base, completedAt: now(), elapsedMs: Date.now() - caseStarted, status: 'completed', result };
        row.usage = validateResult(result, item);
      } catch (error) {
        const safe = safeError(error);
        row = { ...(row || base), completedAt: now(), elapsedMs: Date.now() - caseStarted, status: 'failed', error: safe, usageAccountingIncomplete: true };
        const count = (errorCounts.get(safe.category) || 0) + 1;
        errorCounts.set(safe.category, count);
        if (safe.category.startsWith('IdentityMismatch:') || count >= 3) stopReason = safe.category;
      }
      results[index] = row;
      await save(`${prefix}.json`, row);
      completed += 1;
      console.log(JSON.stringify({ completed, total: 25, id: item.id, status: row.status, decision: row.status === 'completed' ? row.result.decision : null,
        failedPasses: row.usage?.failedPasses ?? null, elapsedMs: row.elapsedMs, stopReason }));
    }
  }
  await Promise.all([worker(), worker()]);
  for (let index = 0; index < 25; index++) if (!results[index]) {
    const item = manifest.cases[index];
    results[index] = { index, id: item.id, mediaSha256: item.sha256, status: 'unattempted', reason: stopReason || 'Execution stopped' };
  }
  const compatible = results.filter(row => row.status === 'completed');
  const receipt = { ...plan, completedAt: now(), elapsedMs: Date.now() - started, status: compatible.length === 25 ? 'completed' : 'completed_with_errors', stopReason,
    counts: { completed: compatible.length, failed: results.filter(row => row.status === 'failed').length, unattempted: results.filter(row => row.status === 'unattempted').length },
    usage: { inputTokensObserved: compatible.reduce((s, row) => s + row.usage.inputTokensObserved, 0), outputTokensObserved: compatible.reduce((s, row) => s + row.usage.outputTokensObserved, 0),
      failedPasses: compatible.reduce((s, row) => s + row.usage.failedPasses, 0), missingUsagePasses: compatible.reduce((s, row) => s + row.usage.missingUsagePasses, 0),
      accountingMayBeIncomplete: true, note: 'Returned pass usage only; SDK retries may not expose billed usage.' }, results };
  await save('receipt.json', receipt);
  console.log(JSON.stringify({ status: receipt.status, counts: receipt.counts, usage: receipt.usage, elapsedMs: receipt.elapsedMs }));
  if (compatible.length !== 25) process.exitCode = 1;
}
main().catch(error => { console.error(JSON.stringify({ status: 'runner_failed', error: safeError(error) })); process.exitCode = 1; });
