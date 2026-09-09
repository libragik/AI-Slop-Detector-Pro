// Exactly two predeclared text-only parents, after the complete negative gate.
import { GoogleGenAI, GenerateVideosOperation } from '@google/genai';
import { createHash, randomUUID } from 'node:crypto';
import { readFile, writeFile, mkdir, stat, rename, open, unlink, realpath, link } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { parseArgs } from 'node:util';
import { spawnSync, spawn } from 'node:child_process';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const scriptPath = fileURLToPath(import.meta.url);
const planPath = path.join(root, 'eval/fixtures/shot-study-generation-plan.json');
const protocolPath = path.join(root, 'eval/AEGIS_SHOT_EVALUATION_PROTOCOL.md');
export const digest = (bytes) => createHash('sha256').update(bytes).digest('hex');
export const hashFile = async (name) => digest(await readFile(name));
const jsonBytes = (value) => JSON.stringify(value, null, 2) + '\n';
const exists = async (name) => { try { await stat(name); return true; } catch (error) { if (error.code === 'ENOENT') return false; throw error; } };
const readJson = async (name) => JSON.parse(await readFile(name, 'utf8'));

export async function atomicJson(name, value) {
  const temporary = name + '.' + randomUUID() + '.tmp';
  const handle = await open(temporary, 'wx');
  try { await handle.writeFile(jsonBytes(value)); await handle.sync(); } finally { await handle.close(); }
  await rename(temporary, name);
}

export async function immutableJson(name, value) {
  const temporary = name + '.' + randomUUID() + '.tmp';
  const handle = await open(temporary, 'wx');
  try { await handle.writeFile(jsonBytes(value)); await handle.sync(); } finally { await handle.close(); }
  try { await link(temporary, name); } finally { await unlink(temporary); }
}

export function operationStatus(operation) {
  if (!operation || typeof operation.name !== 'string' || !/\/operations\/[^/?#]+$/.test(operation.name)) {
    return 'submission_failed_or_uncertain';
  }
  if (operation.done !== undefined && typeof operation.done !== 'boolean') return 'generation_invalid_response';
  if (operation.done !== true) return 'running';
  if (operation.error) return 'generation_failed';
  const response = operation.response;
  if (response?.raiMediaFilteredCount || response?.raiMediaFilteredReasons?.length) return 'generation_filtered';
  const videos = response?.generatedVideos;
  if (videos?.length !== 1 || !videos[0]?.video
      || (!videos[0].video.uri && !videos[0].video.videoBytes)) return 'generation_invalid_response';
  return 'generated';
}

function matchingRecord(record, context) {
  if (record.generationSlot !== context.slot || record.generationPlanSha256 !== context.planSha
      || record.evaluationProtocolSha256 !== context.protocolSha || record.inputMedia?.length !== 0
      || JSON.stringify(record.request) !== JSON.stringify(context.run.request)
      || record.scriptSha256 !== context.scriptSha
      || JSON.stringify(record.runtime) !== JSON.stringify(context.runtime)) throw new Error('Saved operation does not match frozen request/source identity.');
}

export async function finalizeParent(context, record) {
  const { directory, rootDir, slot, planSha, protocolSha, run } = context;
  const receiptPath = path.join(directory, 'receipt.json');
  const videoPath = path.join(directory, 'video.mp4');
  let completed;
  if (await exists(receiptPath)) {
    completed = await readJson(receiptPath);
    matchingRecord(completed, context);
    if (completed.status !== 'succeeded' || operationStatus(completed.operation) !== 'generated') {
      throw new Error('Existing final generation receipt is not a successful registered operation.');
    }
  } else {
    matchingRecord(record, context);
    if (operationStatus(record.operation) !== 'generated') throw new Error('No completed unfiltered generation to finalize.');
    completed = { ...record, status: 'succeeded', finishedAt: new Date().toISOString(),
      output: { path: path.relative(rootDir, videoPath), sha256: await hashFile(videoPath) } };
    await immutableJson(receiptPath, completed);
  }
  if (completed.output?.path !== path.relative(rootDir, videoPath)
      || completed.output.sha256 !== await hashFile(videoPath)) throw new Error('Completed parent bytes changed.');
  const parent = { schemaVersion: 1, status: 'completed', generationSlot: slot,
    generationPlanSha256: planSha, evaluationProtocolSha256: protocolSha, inputMedia: [],
    modelId: run.request.model, modelRevision: 'provider-managed-unpinned', output: completed.output,
    rawGenerationReceipt: { path: path.relative(rootDir, receiptPath), sha256: await hashFile(receiptPath) } };
  const wrapperPath = path.join(directory, 'parent-receipt.json');
  if (await exists(wrapperPath)) {
    if (JSON.stringify(await readJson(wrapperPath)) !== JSON.stringify(parent)) throw new Error('Existing parent wrapper changed.');
  } else await immutableJson(wrapperPath, parent);
  return completed;
}

// Isolate the SDK downloader: its Node implementation pipes a readable into a
// writer, so body-stream errors need not reject the writer's finished promise.
// A child lifetime bounds both that failure and a downloader ignoring abort.
export async function monitorDownload(child, temporary, { timeoutMs = 60000, maxBytes = 50000000 } = {}) {
  let failure;
  let stderr = '';
  child.stderr?.on('data', (chunk) => { stderr = (stderr + chunk.toString()).slice(-4000); });
  let hardKill;
  const stop = (reason) => {
    if (failure) return;
    failure = reason;
    child.kill('SIGTERM');
    hardKill = setTimeout(() => child.kill('SIGKILL'), 250);
  };
  const timer = setTimeout(() => stop('Download exceeded wall-time limit.'), timeoutMs);
  const monitor = setInterval(async () => {
    try { if ((await stat(temporary)).size > maxBytes) stop('Download exceeded byte limit.'); }
    catch (error) { if (error.code !== 'ENOENT') stop('Download size monitoring failed.'); }
  }, 100);
  try {
    const code = await new Promise((resolve, reject) => { child.once('error', reject); child.once('close', resolve); });
    if (failure || code !== 0) throw new Error(failure || `SDK download failed (${code}): ${stderr}`);
    const bytes = (await stat(temporary)).size;
    if (bytes <= 0 || bytes > maxBytes) throw new Error('Generated media byte bound failed.');
    return bytes;
  } finally { clearTimeout(timer); clearTimeout(hardKill); clearInterval(monitor); }
}

async function downloadVideo(video, temporary, apiKey) {
  if (await exists(temporary)) throw new Error('Download attempt path already exists.');
  const code = `import {GoogleGenAI} from '@google/genai'; import {readFileSync} from 'node:fs';
const p=JSON.parse(readFileSync(0,'utf8')); const ai=new GoogleGenAI({apiKey:process.env.GEMINI_API_KEY,enterprise:false,httpOptions:{timeout:60000,retryOptions:{attempts:1}}});
try {await ai.files.download({file:p.video,downloadPath:p.temporary,config:{abortSignal:AbortSignal.timeout(60000),httpOptions:{timeout:60000,retryOptions:{attempts:1}}}});}
catch(e){console.error(String(e.name)+': '+String(e.message));process.exitCode=1;}`;
  const child = spawn(process.execPath, ['--input-type=module', '-e', code], {
    cwd: root, env: { ...process.env, GEMINI_API_KEY: apiKey }, stdio: ['pipe', 'ignore', 'pipe'],
  });
  const monitored = monitorDownload(child, temporary);
  child.stdin.on('error', () => {});
  child.stdin.end(JSON.stringify({ video, temporary }));
  await monitored;
}

export async function verifySavedNegativeGate(gatePath, rootDir = root) {
  const verification = spawnSync(path.join(rootDir, 'eval/.venv/bin/python'), ['-c',
    'import importlib.util,json,sys; from pathlib import Path; p=Path(sys.argv[1]); s=importlib.util.spec_from_file_location("shot_gate",sys.argv[2]); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); r=json.loads(p.read_text()); m.gate_check(p,"negative-45",r["recipeFingerprint"]); print("gate verified")',
    gatePath, path.join(rootDir, 'scripts/eval-aegis-shots.py')], { cwd: rootDir, encoding: 'utf8', timeout: 60000, maxBuffer: 1000000 });
  if (verification.status !== 0) throw new Error('Negative gate failed independent saved-evidence validation.');
}

async function withRunLock(directory, callback) {
  const lockPath = path.join(directory, '.operation.lock');
  let lock;
  for (let retry = 0; retry < 3; retry++) {
    try { lock = await open(lockPath, 'wx'); break; }
    catch (error) {
      if (error.code !== 'EEXIST') throw error;
      const previous = await readJson(lockPath);
      if (!Number.isSafeInteger(previous.pid) || previous.pid <= 0) throw new Error('Unverifiable existing operation lock.');
      try { process.kill(previous.pid, 0); throw new Error('Another process is operating on this generation slot.'); }
      catch (problem) { if (problem.code !== 'ESRCH') throw problem; }
      await rename(lockPath, lockPath + '.stale-' + randomUUID());
    }
  }
  if (!lock) throw new Error('Could not acquire operation lock.');
  await lock.writeFile(jsonBytes({ pid: process.pid }));
  try { return await callback(); }
  finally { await lock.close(); await unlink(lockPath); }
}

export async function main(argv = process.argv.slice(2)) {
const { values, positionals } = parseArgs({ args: argv, allowPositionals: true, options: {
  'plan-sha256': { type: 'string' }, 'protocol-sha256': { type: 'string' },
  'negative-gate': { type: 'string' }, 'gate-sha256': { type: 'string' },
  'price-receipt': { type: 'string' },
} });
const [mode, slot] = positionals;
if (!['submit', 'poll', 'collect', 'check'].includes(mode) || !['V1', 'V2'].includes(slot)
    || positionals.length !== 2) throw new Error('Use submit/poll/collect/check and exactly V1 or V2.');
const local = (name) => {
  if (typeof name !== 'string') throw new Error('A workspace path is required.');
  const result = path.resolve(root, name);
  if (result !== root && !result.startsWith(root + path.sep)) throw new Error('Path escaped workspace.');
  return result;
};
const planBytes = await readFile(planPath);
const plan = JSON.parse(planBytes);
const planSha = digest(planBytes);
const protocolSha = await hashFile(protocolPath);
const sdkPath = fileURLToPath(import.meta.resolve('@google/genai'));
const sdkPackage = await readJson(path.join(root, 'node_modules/@google/genai/package.json'));
if (sdkPackage.version !== '2.21.0') throw new Error('The reviewed @google/genai2.21.0 SDK is required.');
const runtime = { node: process.version, genaiVersion: sdkPackage.version, genaiSourceSha256: await hashFile(sdkPath) };
if (plan.frozen !== true || planSha !== values['plan-sha256'] || protocolSha !== values['protocol-sha256']
    || plan.veoScriptSha256 !== await hashFile(scriptPath)) throw new Error('Frozen generation source/plan mismatch.');
const selected = plan.veoRuns.filter((run) => run.id === slot);
if (selected.length !== 1) throw new Error('Missing unique fixed generation slot.');
const run = selected[0];
if (run.maxNewSubmissions !== 1 || run.inputMedia.length || run.request.model !== 'veo-3.1-generate-preview'
    || Object.keys(run.request).sort().join() !== 'config,model,source'
    || Object.keys(run.request.source).join() !== 'prompt'
    || typeof run.request.source.prompt !== 'string' || !run.request.source.prompt
    || run.request.config.numberOfVideos !== 1 || run.request.config.durationSeconds !== 8
    || run.request.config.resolution !== '720p' || run.request.config.aspectRatio !== '16:9'
    || Object.keys(run.request.config).sort().join() !== 'aspectRatio,durationSeconds,numberOfVideos,resolution') {
  throw new Error('Only the fixed text-only eight-second single-video request is supported.');
}
const gatePath = local(values['negative-gate']);
if (await hashFile(gatePath) !== values['gate-sha256']) throw new Error('Negative gate receipt hash mismatch.');
const gate = JSON.parse(await readFile(gatePath, 'utf8'));
if (gate.status !== 'passed' || gate.stage !== 'negative-45'
    || gate.configuration.generationPlanSha256 !== planSha
    || gate.configuration.protocolSha256 !== protocolSha) throw new Error('The fixed negative gate must pass first.');
await verifySavedNegativeGate(gatePath);
if (mode === 'check') {
  console.log(JSON.stringify({ slot, gate: 'passed', planSha256: planSha, networkRequests: 0 }));
  return;
}
const directory = local(run.outputDir);
if (!directory.startsWith(path.join(root, 'eval/runs') + path.sep)) throw new Error('Generation output must be under eval/runs.');
const recordPath = path.join(directory, 'state.json');
const context = { directory, rootDir: root, slot, planSha, protocolSha, run, runtime, scriptSha: await hashFile(scriptPath) };
const apiKey = process.env.GEMINI_API_KEY || process.env.GOOGLE_API_KEY;
const clean = (value) => JSON.parse(apiKey ? JSON.stringify(value).replaceAll(apiKey, '[REDACTED]') : JSON.stringify(value));
const persist = async (record) => atomicJson(recordPath, clean(record));
const client = () => {
  if (!apiKey) throw new Error('A configured Gemini key is required for this network operation.');
  return new GoogleGenAI({ apiKey, enterprise: false, httpOptions: { timeout: 30000, retryOptions: { attempts: 1 } } });
};
if (mode !== 'submit') {
  const canonical = await realpath(directory);
  if (canonical !== directory) throw new Error('Generation directory must not be a symlink.');
  if (await exists(path.join(directory, 'receipt.json'))) {
    await withRunLock(directory, async () => finalizeParent(context));
    console.log(JSON.stringify({ slot, status: 'succeeded', resumedFinalization: true, networkRequests: 0 }));
    return;
  }
}

if (mode === 'submit') {
  const ai = client();
  const pricePath = local(values['price-receipt']);
  const price = JSON.parse(await readFile(pricePath, 'utf8'));
  const age = Date.now() - Date.parse(price.verifiedAt);
  if (price.model !== run.request.model || price.currency !== 'USD' || price.unit !== 'second'
      || !(price.pricePerSecond > 0 && price.pricePerSecond <= 0.4)
      || !Number.isFinite(age) || age < 0 || age > 3600000
      || !String(price.sourceUrl).startsWith('https://ai.google.dev/')) {
    throw new Error('A current official price receipt within the fixed USD6.40 study budget is required.');
  }
  if (slot === 'V2') {
    const first = plan.veoRuns.find((item) => item.id === 'V1');
    const prior = JSON.parse(await readFile(path.join(local(first.outputDir), 'receipt.json'), 'utf8'));
    matchingRecord(prior, { ...context, slot: 'V1', run: first });
    const firstVideo = path.join(local(first.outputDir), 'video.mp4');
    if (prior.status !== 'succeeded' || prior.generationPlanSha256 !== planSha
        || prior.evaluationProtocolSha256 !== protocolSha
        || operationStatus(prior.operation) !== 'generated'
        || prior.output?.path !== path.relative(root, firstVideo)
        || await hashFile(firstVideo) !== prior.output.sha256) {
      throw new Error('First registered Veo parent must have succeeded; do not replace a failed parent.');
    }
  }
  await mkdir(directory, { recursive: false });
  const canonical = await realpath(directory);
  if (canonical !== directory) throw new Error('Generation directory must not be a symlink.');
  await withRunLock(directory, async () => {
  const record = { schemaVersion: 1, status: 'submitting', generationSlot: slot,
    startedAt: new Date().toISOString(), generationPlanSha256: planSha,
    evaluationProtocolSha256: protocolSha, scriptSha256: await hashFile(scriptPath),
    inputMedia: [], request: run.request, runtime, output: null,
    negativeGate: { path: path.relative(root, gatePath), sha256: await hashFile(gatePath) },
    priceReceipt: { path: path.relative(root, pricePath), sha256: await hashFile(pricePath) },
    downloadAttempts: [], pollAttempts: [] };
  await writeFile(recordPath, JSON.stringify(record, null, 2) + '\n', { flag: 'wx' });
  await writeFile(path.join(directory, 'generation-plan.json'), planBytes, { flag: 'wx' });
  await writeFile(path.join(directory, 'submitted-script.mjs'), await readFile(scriptPath), { flag: 'wx' });
  await writeFile(path.join(directory, 'evaluation-protocol.md'), await readFile(protocolPath), { flag: 'wx' });
  await writeFile(path.join(directory, 'negative-gate.json'), await readFile(gatePath), { flag: 'wx' });
  await writeFile(path.join(directory, 'price-receipt.json'), await readFile(pricePath), { flag: 'wx' });
  let operation;
  try {
    operation = await ai.models.generateVideos(structuredClone(run.request));
  } catch (error) {
    record.status = 'submission_failed_or_uncertain';
    record.error = { name: error.name, message: String(error.message) };
    await persist(record);
    console.log(JSON.stringify(clean({ slot, status: record.status, error: record.error })));
    process.exitCode = 1;
    return;
  }
  // Preserve the sole submission response independently of mutable state. If a
  // subsequent state write fails, poll/collect can recover this exact operation.
  console.log(JSON.stringify({ slot, submissionAcknowledged: true, operationName: operation.name }));
  await immutableJson(path.join(directory, 'submission-response.json'), clean({
    generationSlot: slot, generationPlanSha256: planSha, operation,
  }));
  record.operation = operation;
  record.status = operationStatus(operation);
  await persist(record);
  console.log(JSON.stringify({ slot, status: record.status, operationName: operation.name }));
  if (!['running', 'generated'].includes(record.status)) process.exitCode = 1;
  });
} else {
  await withRunLock(directory, async () => {
  const record = JSON.parse(await readFile(recordPath, 'utf8'));
  matchingRecord(record, context);
  if (!record.operation?.name && await exists(path.join(directory, 'submission-response.json'))) {
    const response = await readJson(path.join(directory, 'submission-response.json'));
    if (response.generationSlot !== slot || response.generationPlanSha256 !== planSha) throw new Error('Recovered operation source mismatch.');
    record.operation = response.operation;
    record.status = operationStatus(record.operation);
    await persist(record);
  }
  if (record.generationSlot !== slot || record.generationPlanSha256 !== planSha
      || record.evaluationProtocolSha256 !== protocolSha
      || JSON.stringify(record.request) !== JSON.stringify(run.request) || !record.operation?.name) {
    throw new Error('No matching submitted operation; never repeat an uncertain submission.');
  }
  if (mode === 'poll') {
    const status = operationStatus(record.operation);
    if (!record.operation.done) {
      const ai = client();
      const operation = Object.assign(new GenerateVideosOperation(), record.operation);
      const attempt = { number: record.pollAttempts.length + 1, startedAt: new Date().toISOString(), status: 'polling' };
      record.pollAttempts.push(attempt);
      await persist(record);
      try {
      const updated = await ai.operations.getVideosOperation({ operation });
      if (updated.name !== operation.name) throw new Error('Poll response changed the registered operation identity.');
      record.operation = updated;
      record.polledAt = new Date().toISOString();
      record.status = operationStatus(updated);
      attempt.status = 'succeeded';
      attempt.finishedAt = record.polledAt;
      await persist(record);
      } catch (error) {
        attempt.status = 'failed';
        attempt.error = { name: error.name, message: String(error.message) };
        await persist(record);
        throw new Error(clean(attempt.error).message);
      }
    }
    console.log(JSON.stringify({ slot, status: record.status, done: record.operation.done,
      generatedCount: record.operation.response?.generatedVideos?.length ?? 0 }));
    if (!['running', 'generated'].includes(record.operation.done ? operationStatus(record.operation) : status)) process.exitCode = 1;
  } else {
    // A validated download is a transaction boundary: recover a crash before or
    // after rename without making another HTTP request or rewriting final proof.
    const validatedPath = path.join(directory, 'validated-download.json');
    if (await exists(validatedPath)) {
      const validated = await readJson(validatedPath);
      if (validated.operationName !== record.operation.name || validated.generationPlanSha256 !== planSha
          || validated.generationSlot !== slot) throw new Error('Validated download belongs to another generation.');
      const finalPath = path.join(directory, 'video.mp4');
      const candidate = await exists(finalPath) ? finalPath : local(validated.temporaryPath);
      if (await hashFile(candidate) !== validated.sha256) throw new Error('Validated download bytes changed.');
      if (candidate !== finalPath) await rename(candidate, finalPath);
      record.probe = validated.probe;
      await finalizeParent(context, clean(record));
      console.log(JSON.stringify({ slot, status: 'succeeded', resumedFinalization: true, networkRequests: 0 }));
      return;
    }
    const videos = record.operation.response?.generatedVideos;
    if (operationStatus(record.operation) !== 'generated') {
      throw new Error('Exactly one completed, unfiltered, uncollected generation is required.');
    }
    const attempt = { number: record.downloadAttempts.length + 1, startedAt: new Date().toISOString(), status: 'downloading' };
    const temporary = path.join(directory, `video-attempt-${attempt.number}.part`);
    record.downloadAttempts.push(attempt);
    await persist(record);
    try {
      if (!apiKey) throw new Error('A configured Gemini key is required to download media.');
      await downloadVideo(videos[0].video, temporary, apiKey);
      const size = (await stat(temporary)).size;
      if (size <= 0 || size > 50000000) throw new Error('Generated media byte bound failed.');
      const checked = spawnSync('ffprobe', ['-v', 'error', '-show_streams', '-show_format', '-of', 'json', temporary],
        { encoding: 'utf8', timeout: 15000, maxBuffer: 1000000 });
      if (checked.status !== 0) throw new Error('Generated media did not probe successfully.');
      const probe = JSON.parse(checked.stdout);
      const video = probe.streams.filter((stream) => stream.codec_type === 'video');
      if (video.length !== 1 || video[0].width !== 1280 || video[0].height !== 720
          || video[0].avg_frame_rate !== '24/1' || Number(video[0].nb_frames) !== 192
          || Math.abs(Number(video[0].duration) - 8) > 0.001) throw new Error('Generation dimensions/cadence differ from the fixed parent.');
      const finalPath = path.join(directory, 'video.mp4');
      try { await stat(finalPath); throw new Error('Prior parent exists.'); } catch (error) { if (error.code !== 'ENOENT') throw error; }
      await immutableJson(validatedPath, { generationSlot: slot, generationPlanSha256: planSha,
        operationName: record.operation.name, temporaryPath: path.relative(root, temporary),
        sha256: await hashFile(temporary), probe });
      attempt.status = 'succeeded';
      attempt.finishedAt = new Date().toISOString();
      record.probe = probe;
      record.status = 'download_validated';
      await persist(record);
    } catch (error) {
      attempt.status = 'failed';
      attempt.error = { name: error.name, message: String(error.message) };
      record.status = 'download_or_validation_failed';
      await persist(record);
      throw new Error(clean(attempt.error).message);
    }
    // Final proof is immutable; wrapper failure must never demote or rewrite it.
    const validated = await readJson(validatedPath);
    const finalPath = path.join(directory, 'video.mp4');
    if (await hashFile(temporary) !== validated.sha256) throw new Error('Validated download changed before rename.');
    await rename(temporary, finalPath);
    const completed = await finalizeParent(context, clean(record));
    console.log(JSON.stringify({ slot, status: 'succeeded', output: completed.output }));
  }
  });
}
}

if (process.argv[1] && path.resolve(process.argv[1]) === scriptPath) {
  main().catch((error) => { console.error(JSON.stringify({ status: 'failed', errorType: error.name, message: String(error.message) })); process.exitCode = 1; });
}
