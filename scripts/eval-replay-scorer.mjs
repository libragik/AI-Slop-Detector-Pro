#!/usr/bin/env node
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { resolve, dirname, relative } from "node:path";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import { parseArgs } from "node:util";
import { report, wilson } from "../eval/metrics.mjs";
import { replayRow } from "../eval/replay.mjs";

const { values } = parseArgs({ options: {
  input: { type: "string" }, output: { type: "string" },
  unseal: { type: "boolean", default: false },
} });
// No saved prediction or run metadata is opened before this explicit guard.
if (!values.input || !values.output || !values.unseal) throw new Error("Requires --input RUN_DIR --output NEW_DIR --unseal after explicit final policy freeze");
const root = process.cwd();
const input = resolve(values.input), output = resolve(values.output);
if (input === output || output.startsWith(input + "/") || input.startsWith(output + "/")) throw new Error("Replay must use a separate, non-nested output directory");
const hash = data => createHash("sha256").update(data).digest("hex");
const parseLines = data => data.trim().split("\n").filter(Boolean).map(line => JSON.parse(line));
const sourcePaths = [
  "src/lib/analyzer/scoring.ts", "src/lib/analyzer/evidence-consistency.ts",
  "src/lib/analyzer/evidence-time.ts", "src/lib/analyzer/types.ts",
  "src/lib/analyzer/detection-policy.ts", "src/lib/analyzer/pipeline.ts",
  "scripts/eval-replay-scorer.mjs", "eval/replay.mjs", "eval/metrics.mjs", "pnpm-lock.yaml",
];
const sourceBytes = await Promise.all(sourcePaths.sort().map(async path => ({ path, bytes: await readFile(resolve(root, path)) })));
const sourceFiles = sourceBytes.map(({ path, bytes }) => ({ path, sha256: hash(bytes) }));
for (const file of sourceFiles) if (hash(await readFile(resolve(root, file.path))) !== file.sha256) throw new Error("Scorer changed while snapshotting; retry before unsealing");
const policySource = sourceBytes.find(file => file.path.endsWith("detection-policy.ts")).bytes.toString();
const policyVersion = policySource.match(/DETECTOR_POLICY_VERSION\s*=\s*"([^"]+)"/)?.[1];
if (!policyVersion) throw new Error("Cannot determine replay policy version");

// Exclusive directory creation prevents overwriting an earlier experiment.
await mkdir(dirname(output), { recursive: true });
await mkdir(output);
const snapshotRoot = resolve(output, "source");
for (const { path, bytes } of sourceBytes) {
  const target = resolve(snapshotRoot, path);
  await mkdir(dirname(target), { recursive: true });
  await writeFile(target, bytes);
}
const esbuild = createRequire(import.meta.resolve("tsx/package.json"))("esbuild");
const bundlePath = resolve(output, "scorer.mjs");
const build = await esbuild.build({
  entryPoints: [resolve(snapshotRoot, "src/lib/analyzer/scoring.ts")], outfile: bundlePath,
  absWorkingDir: snapshotRoot, bundle: true, platform: "node", format: "esm", target: "node22", metafile: true,
});
for (const file of Object.keys(build.metafile.inputs)) {
  const path = relative(snapshotRoot, resolve(snapshotRoot, file));
  if (!sourceFiles.some(source => source.path === path)) throw new Error("Scorer dependency is outside the audited snapshot");
}
if (Object.values(build.metafile.outputs).some(file => file.imports.length)) throw new Error("Offline scorer bundle must have no runtime imports");
await writeFile(resolve(output, "scorer-build.json"), JSON.stringify(build.metafile, null, 2) + "\n");
const bundleSha256 = hash(await readFile(bundlePath));
const { aggregateScore } = await import(pathToFileURL(bundlePath).href);

const predictionBytes = await readFile(resolve(input, "predictions.jsonl"));
const planBytes = await readFile(resolve(input, "plan.json"));
const originalPlan = JSON.parse(planBytes.toString());
const originalRows = parseLines(predictionBytes.toString());
if (new Set(originalRows.map(row => row.id)).size !== originalRows.length) throw new Error("Duplicate source prediction IDs");
const provenance = {
  mode: "offline-score-replay", policyVersion, modelRequests: 0,
  sourceFingerprint: hash(JSON.stringify(sourceFiles)), bundleSha256,
  originalRun: input, originalPredictionSha256: hash(predictionBytes),
};
const replay = originalRows.map(row => replayRow(row, aggregateScore, provenance));
const rows = replay.map(item => item.row);
const changes = replay.map(item => item.changes).filter(Boolean);
const equivalence = {
  ...provenance, attempted: rows.length, replayed: changes.length,
  retainedErrors: rows.filter(row => row.error).length,
  decisionsEquivalent: changes.every(change => !change.decisionChanged),
  everyScoreFieldEquivalent: changes.every(change => change.changedScoreFields.length === 0),
  changedDecisionCount: changes.filter(change => change.decisionChanged).length,
  changedScoreCount: changes.filter(change => change.changedScoreFields.length > 0).length,
  changes,
  caveat: "Only the deterministic score aggregator was replayed. Model observations, prompts, media, pass status, token usage and original latency were retained. This is not a new full-pipeline API run. Original analyzerVersion and detectorFingerprint identify observation collection; scoreReplay identifies the new decision policy.",
};
const plan = {
  ...Object.fromEntries(["manifestSha256", "selected", "sourceGroups", "split", "labels"].map(key => [key, originalPlan[key]])),
  ...provenance, execution: "offline-score-replay", sourceFiles,
  originalPlanSha256: hash(planBytes), originalPlan,
};
const summary = { ...report(rows), plan, selection: {
  selected: originalPlan.selected, attempted: rows.length,
  notAttempted: Math.max(0, originalPlan.selected - rows.length),
  completionRate: wilson(rows.filter(row => !row.error).length, originalPlan.selected),
} };
await writeFile(resolve(output, "predictions.jsonl"), rows.map(row => JSON.stringify(row) + "\n").join(""));
await writeFile(resolve(output, "plan.json"), JSON.stringify(plan, null, 2) + "\n");
await writeFile(resolve(output, "report.json"), JSON.stringify(summary, null, 2) + "\n");
await writeFile(resolve(output, "replay-equivalence.json"), JSON.stringify(equivalence, null, 2) + "\n");
if (hash(await readFile(resolve(input, "predictions.jsonl"))) !== hash(predictionBytes) || hash(await readFile(resolve(input, "plan.json"))) !== hash(planBytes)) throw new Error("Source run changed during replay");
if (hash(await readFile(bundlePath)) !== bundleSha256) throw new Error("Frozen scorer bundle changed during replay");
console.log(JSON.stringify({ output, policyVersion, replayed: changes.length,
  decisionsEquivalent: equivalence.decisionsEquivalent, everyScoreFieldEquivalent: equivalence.everyScoreFieldEquivalent,
  changedDecisionCount: equivalence.changedDecisionCount, changedScoreCount: equivalence.changedScoreCount }, null, 2));
