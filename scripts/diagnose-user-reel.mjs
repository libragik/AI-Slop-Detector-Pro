#!/usr/bin/env node
// One user-reported case, without inventing benchmark ground truth.
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { resolve, dirname } from "node:path";
import { pathToFileURL } from "node:url";

const root = process.cwd();
const output = resolve(root, "eval/runs/user-reel-Da7nZ5hs6H7-gemini-v1");
const mediaPath = "eval/media/user-reel-Da7nZ5hs6H7/57be227b22cb166521cf698611886f6380c7f658a41217d03842395c63d270db.mp4";
const expectedHash = "57be227b22cb166521cf698611886f6380c7f658a41217d03842395c63d270db";
const hash = bytes => createHash("sha256").update(bytes).digest("hex");
const media = await readFile(resolve(root, mediaPath));
if (hash(media) !== expectedHash) throw new Error("User case media hash mismatch");
const nextRequire = createRequire(import.meta.resolve("next/package.json"));
nextRequire("@next/env").loadEnvConfig(root);
if (!(process.env.GEMINI_API_KEY || process.env.GOOGLE_API_KEY)) throw new Error("Gemini credential is missing");
await mkdir(output, { recursive: true });
const tsxRequire = createRequire(import.meta.resolve("tsx/package.json"));
const build = await tsxRequire("esbuild").build({
  entryPoints: [resolve(root, "src/lib/analyzer/evaluation.ts")],
  absWorkingDir: root, bundle: true, packages: "external", platform: "node",
  format: "esm", target: "node22", metafile: true, write: false,
});
const files = [...new Set([...Object.keys(build.metafile.inputs), "scripts/diagnose-user-reel.mjs", "pnpm-lock.yaml"])].sort();
const source = [];
for (const path of files) {
  const bytes = await readFile(resolve(root, path));
  source.push({ path, sha256: hash(bytes) });
  const target = resolve(output, "source", path);
  if (!target.startsWith(resolve(output, "source") + "/")) throw new Error("Unexpected source path");
  await mkdir(dirname(target), { recursive: true });
  await writeFile(target, bytes, { flag: "wx" });
}
const bundle = build.outputFiles[0].contents;
await writeFile(resolve(output, "adapter.mjs"), bundle, { flag: "wx" });
await writeFile(resolve(output, "adapter-build.json"), JSON.stringify(build.metafile, null, 2) + "\n", { flag: "wx" });
const started = Date.now();
const plan = {
  kind: "user-case-diagnosis", groundTruth: null, userReportedOrigin: "AI",
  mediaPath, mediaSha256: expectedHash, bytes: media.length,
  neutralUploadFilename: "video-under-review.mp4", sourceCaptionSentToModel: false,
  adapterExport: "analyzeEvaluationVideo", bundleSha256: hash(bundle), source,
  node: process.version, startedAt: new Date(started).toISOString(),
  execution: "current-app-video-only-adapter", applicationRetryPolicyPreserved: true,
};
// Exclusive claim before any external inference. Never retry this case automatically.
await writeFile(resolve(output, "execution.json"), JSON.stringify(plan, null, 2) + "\n", { flag: "wx" });
const adapter = await import(pathToFileURL(resolve(output, "adapter.mjs")).href);
try {
  const result = await adapter.analyzeEvaluationVideo({ path: resolve(root, mediaPath), mimeType: "video/mp4" });
  const receipt = { ...plan, completedAt: new Date().toISOString(), elapsedMs: Date.now() - started, status: "completed", result };
  // Provider results are local debugging data; keep credentials out even on unexpected content.
  let serialized = JSON.stringify(receipt, null, 2);
  for (const key of [process.env.GEMINI_API_KEY, process.env.GOOGLE_API_KEY, process.env.SIGHTENGINE_API_USER, process.env.SIGHTENGINE_API_SECRET]) {
    if (key) serialized = serialized.replaceAll(key, "[REDACTED]");
  }
  await writeFile(resolve(output, "receipt.json"), serialized + "\n", { flag: "wx" });
  console.log(JSON.stringify({ status: "completed", verdict: result.verdict, confidence: result.confidence, decision: result.decision, elapsedMs: receipt.elapsedMs }));
} catch {
  const receipt = { ...plan, completedAt: new Date().toISOString(), elapsedMs: Date.now() - started,
    status: "failed", error: "Current detector case evaluation failed; no automatic rerun. Provider error text omitted." };
  await writeFile(resolve(output, "receipt.json"), JSON.stringify(receipt, null, 2) + "\n", { flag: "wx" });
  console.error(receipt.error);
  process.exitCode = 1;
}
