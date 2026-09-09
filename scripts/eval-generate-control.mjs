// One development control with first-party generation evidence. Never auto-retry a submission.
import { GoogleGenAI, GenerateVideosOperation } from '@google/genai';
import { createHash } from 'node:crypto';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const runDir = path.join(root, 'eval/runs/generated-origin-control');
const recordPath = path.join(runDir, 'generation.json');
const planPath = path.join(root, 'eval/fixtures/video-generation-plan.json');
const apiKey = process.env.GEMINI_API_KEY || process.env.GOOGLE_API_KEY;
if (!apiKey) throw new Error('A configured Gemini key is required.');
const ai = new GoogleGenAI({ apiKey, httpOptions: { timeout: 30000, retryOptions: { attempts: 1 } } });
const mode = process.argv[2];
const sha256 = (value) => createHash('sha256').update(value).digest('hex');
const clean = (value) => JSON.parse(JSON.stringify(value).replaceAll(apiKey, '[REDACTED]'));
const persist = async (record) => writeFile(recordPath, JSON.stringify(clean(record), null, 2) + '\n');

if (mode === 'generate') {
  const planBytes = await readFile(planPath);
  const plan = JSON.parse(planBytes);
  if (plan.request.model !== 'veo-3.1-generate-preview' || plan.request.config.numberOfVideos !== 1
      || plan.request.config.durationSeconds !== 8 || plan.request.config.resolution !== '720p'
      || Object.keys(plan.request).some((key) => !['model', 'prompt', 'config'].includes(key))) {
    throw new Error('This helper is bounded to the declared single text-only control.');
  }
  await mkdir(runDir, { recursive: true });
  const record = { status: 'submitting', startedAt: new Date().toISOString(), planSha256: sha256(planBytes),
    scriptSha256: sha256(await readFile(fileURLToPath(import.meta.url))), request: plan.request, inputMedia: [] };
  await writeFile(recordPath, JSON.stringify(record, null, 2) + '\n', { flag: 'wx' });
  try {
    record.operation = await ai.models.generateVideos(plan.request);
    record.status = record.operation.done ? 'completed' : 'running';
    await persist(record);
    console.log(JSON.stringify({ status: record.status, operation: record.operation.name, recordPath }));
  } catch (error) {
    record.status = 'submission_failed_or_uncertain';
    record.error = { name: error.name, message: String(error.message) };
    await persist(record);
    console.log(JSON.stringify({ status: record.status, error: clean(record.error), recordPath }));
    process.exitCode = 1;
  }
} else if (mode === 'poll') {
  const record = JSON.parse(await readFile(recordPath, 'utf8'));
  if (!record.operation?.name) throw new Error('No operation to resume; do not repeat submission.');
  if (!record.operation.done) {
    // JSON persistence drops the SDK operation prototype; restore it when resuming.
    const operation = Object.assign(new GenerateVideosOperation(), record.operation);
    record.operation = await ai.operations.getVideosOperation({ operation });
    record.pollScriptSha256 = sha256(await readFile(fileURLToPath(import.meta.url)));
    record.polledAt = new Date().toISOString();
    record.status = record.operation.done ? (record.operation.error ? 'failed' : 'completed') : 'running';
    await persist(record);
  }
  const generated = record.operation.response?.generatedVideos || [];
  console.log(JSON.stringify({ status: record.status, done: record.operation.done, operation: record.operation.name,
    generatedCount: generated.length, error: record.operation.error,
    filteredCount: record.operation.response?.raiMediaFilteredCount,
    videoMetadata: generated.map(({ video }) => ({ mimeType: video?.mimeType, hasUri: Boolean(video?.uri) })) }));
} else {
  throw new Error('Use generate once or poll to resume the existing operation.');
}
