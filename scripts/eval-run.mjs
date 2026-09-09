#!/usr/bin/env node
import { createHash } from "node:crypto";
import { readFile, writeFile, appendFile, mkdir, readdir } from "node:fs/promises";
import { resolve, dirname, relative } from "node:path";
import { pathToFileURL } from "node:url";
import { parseArgs } from "node:util";
import { createRequire } from "node:module";
import { decisionOf, report, wilson } from "../eval/metrics.mjs";

const { values } = parseArgs({ options: {
  manifest: { type: "string", default: "eval/manifest.jsonl" },
  adapter: { type: "string", default: "src/lib/analyzer/evaluation.ts" },
  export: { type: "string", default: "analyzeEvaluationVideo" },
  output: { type: "string" }, run: { type: "boolean", default: false },
  split: { type: "string", default: "development" }, limit: { type: "string" },
  concurrency: { type: "string", default: "1" }, resume: { type: "boolean", default: false },
  "retry-errors": { type: "boolean", default: false },
  predictions: { type: "string" },
} });
const root = process.cwd();
const hash = bytes => createHash("sha256").update(bytes).digest("hex");
async function sourceFingerprint() {
  const files = [values.adapter, "scripts/eval-run.mjs", "eval/metrics.mjs", "src/lib/config/env.ts", "pnpm-lock.yaml", "eval/baseline-gemini.ts.txt", "eval/baseline-scoring.ts.txt", "eval/baseline-video-schema.json",
    ...(await readdir(resolve(root, "src/lib/analyzer"))).filter(name => name.endsWith(".ts")).map(name => `src/lib/analyzer/${name}`)];
  const hashes = await Promise.all([...new Set(files)].sort().map(async path => ({ path, sha256: hash(await readFile(resolve(root, path))) })));
  return { digest: hash(JSON.stringify(hashes)), files: hashes };
}
async function freezeAdapter(output, source) {
  const snapshotRoot = resolve(output, "source");
  for (const entry of source.files) {
    const bytes = await readFile(resolve(root, entry.path));
    if (hash(bytes) !== entry.sha256) throw new Error("Detector changed while snapshotting; retry before making model calls");
    const target = resolve(snapshotRoot, relative(root, resolve(root, entry.path)));
    if (!target.startsWith(snapshotRoot + "/")) throw new Error("Adapter must be inside the repository");
    await mkdir(dirname(target), { recursive: true });
    await writeFile(target, bytes);
  }
  const tsxRequire = createRequire(import.meta.resolve("tsx/package.json"));
  const esbuild = tsxRequire("esbuild");
  const bundlePath = resolve(output, "adapter.mjs");
  const result = await esbuild.build({
    entryPoints: [resolve(root, values.adapter)], outfile: bundlePath,
    absWorkingDir: root, bundle: true, packages: "external", platform: "node", format: "esm",
    target: "node22", metafile: true,
    // The baseline adapter's relative data-file read resolves to the preserved
    // prompt and schema snapshots, while all executable local imports enter this bundle.
    define: { "import.meta.url": JSON.stringify(pathToFileURL(resolve(snapshotRoot, values.adapter)).href) },
  });
  if ((await sourceFingerprint()).digest !== source.digest) throw new Error("Detector changed while bundling; retry before making model calls");
  await writeFile(resolve(output, "adapter-build.json"), JSON.stringify(result.metafile, null, 2) + "\n");
  return { path: bundlePath, sha256: hash(await readFile(bundlePath)) };
}
const manifestBytes = await readFile(resolve(root, values.manifest));
const manifest = manifestBytes.toString().trim().split("\n").filter(Boolean).map(line => JSON.parse(line));
const ids = new Set(), groupSplits = new Map(), hashSplits = new Map();
for (const row of manifest) {
  if (!row.id || ids.has(row.id)) throw new Error(`Duplicate/missing manifest id: ${row.id}`);
  ids.add(row.id);
  for (const field of ["groupId", "split", "path", "sha256", "sourceUrl", "license", "groundTruth"]) {
    if (!row[field]) throw new Error(`Missing ${field} for ${row.id}`);
  }
  if (!["real", "ai", "cgi", "mixed"].includes(row.label)) throw new Error(`Unknown truth label: ${row.label}`);
  if (!["development", "calibration", "holdout"].includes(row.split)) throw new Error(`Unknown split: ${row.split}`);
  for (const [mapping, key] of [[groupSplits, row.groupId], [hashSplits, row.sha256]]) {
    if (mapping.has(key) && mapping.get(key) !== row.split) throw new Error(`Cross-split leakage: ${key}`);
    mapping.set(key, row.split);
  }
}
let selected = manifest.filter(row => values.split === "all" || row.split === values.split);
if (values.limit !== undefined) {
  if (!Number.isInteger(Number(values.limit)) || Number(values.limit) < 1) throw new Error("Limit must be a positive integer");
  selected = selected.slice(0, Number(values.limit));
}
if (selected.length === 0) throw new Error("No clips selected");
for (const row of selected) {
  if (hash(await readFile(resolve(root, row.path))) !== row.sha256) throw new Error(`Hash mismatch: ${row.id}`);
}
const plan = { manifestSha256: hash(manifestBytes), selected: selected.length,
  sourceGroups: new Set(selected.map(row => row.groupId)).size,
  split: values.split, labels: Object.fromEntries([...new Set(selected.map(row => row.label))].map(label => [label, selected.filter(row => row.label === label).length])),
  adapter: values.adapter, adapterExport: values.export };
const selectedById = new Map(selected.map(row => [row.id, row]));
function verifyPredictions(rows) {
  if (new Set(rows.map(row => row.id)).size !== rows.length) throw new Error("Duplicate prediction IDs");
  for (const row of rows) {
    const truth = selectedById.get(row.id);
    if (!truth || truth.sha256 !== row.sha256) throw new Error(`Prediction does not match selected corpus: ${row.id}`);
    Object.assign(row, truth);
  }
}

if (!values.run && !values.predictions) {
  console.log(JSON.stringify({ mode: "validated-dry-run", ...plan }, null, 2));
} else {
  const output = resolve(root, values.output ?? `eval/runs/${new Date().toISOString().replaceAll(":", "-")}`);
  await mkdir(output, { recursive: true });
  let rows = [];
  if (values.predictions) {
    rows = (await readFile(resolve(root, values.predictions), "utf8")).trim().split("\n").filter(Boolean).map(JSON.parse);
    // Always use manifest truth, not labels provided by a prediction file.
    verifyPredictions(rows);
  } else {
    const nextRequire = createRequire(import.meta.resolve("next/package.json"));
    nextRequire("@next/env").loadEnvConfig(root);
    const source = await sourceFingerprint();
    const envSource = await readFile(resolve(root, "src/lib/config/env.ts"), "utf8");
    const configNames = [...new Set([...envSource.matchAll(/process\.env\.([A-Z0-9_]+)|(?:integerEnv|booleanEnv)\("([A-Z0-9_]+)"/g)]
      .map(match => match[1] ?? match[2]).filter(name => !/(KEY|TOKEN|SECRET|PASSWORD)/.test(name)))].sort();
    plan.sourceFingerprint = source.digest;
    plan.sourceFiles = source.files;
    // Record only a digest of non-secret configuration values. Credentials are
    // excluded, so restoring a missing key can safely retry failed requests.
    plan.configurationFingerprint = hash(JSON.stringify(configNames.map(name => [name, process.env[name] ?? null])));
    plan.nodeVersion = process.version;
    let bundle;
    if (values["retry-errors"] && !values.resume) throw new Error("--retry-errors requires --resume");
    if (values.resume) {
      try {
        const priorPlan = JSON.parse(await readFile(resolve(output, "plan.json"), "utf8"));
        if (["manifestSha256", "split", "selected", "adapter", "adapterExport", "sourceFingerprint", "configurationFingerprint", "nodeVersion"].some(key => priorPlan[key] !== plan[key])) throw new Error("Resume configuration or source differs from saved run; start a fresh experiment");
        rows = (await readFile(resolve(output, "predictions.jsonl"), "utf8")).trim().split("\n").filter(Boolean).map(JSON.parse);
        verifyPredictions(rows);
        bundle = { path: resolve(output, "adapter.mjs"), sha256: priorPlan.adapterBundleSha256 };
        if (!bundle.sha256 || hash(await readFile(bundle.path)) !== bundle.sha256) throw new Error("Saved adapter bundle is missing or has changed");
        // A retried row replaces its earlier error in the active predictions,
        // while the original evidence is retained in a timestamped archive.
        if (values["retry-errors"]) {
          const errors = rows.filter(row => row.error);
          if (errors.length) await writeFile(resolve(output, `prior-errors-${Date.now()}.jsonl`), errors.map(row => JSON.stringify(row) + "\n").join(""));
          rows = rows.filter(row => !row.error);
          await writeFile(resolve(output, "predictions.jsonl"), rows.map(row => JSON.stringify(row) + "\n").join(""));
        }
      } catch (error) {
        if (error.code === "ENOENT") throw new Error("Cannot resume: saved run files are incomplete", { cause: error });
        throw error;
      }
    } else {
      // Never append a new experiment to an existing predictions file.
      await writeFile(resolve(output, "predictions.jsonl"), "", { flag: "wx" });
    }
    bundle ??= await freezeAdapter(output, source);
    plan.adapterBundleSha256 = bundle.sha256;
    plan.execution = "immutable-local-source-bundle";
    await writeFile(resolve(output, "plan.json"), JSON.stringify(plan, null, 2) + "\n");
    const adapter = await import(pathToFileURL(bundle.path).href);
    const analyze = adapter[values.export];
    if (typeof analyze !== "function") throw new Error("Adapter export is not a function");
    const complete = new Set(rows.map(row => row.id));
    const queue = selected.filter(row => !complete.has(row.id));
    const concurrency = Number(values.concurrency);
    if (!Number.isInteger(concurrency) || concurrency < 1 || concurrency > 4) throw new Error("Concurrency must be 1 through 4");
    let consecutiveErrors = 0, lastError = null, aborted = null;
    await Promise.all(Array.from({ length: concurrency }, async () => {
      while (queue.length && !aborted) {
        const item = queue.shift();
        const started = Date.now();
        let row;
        try {
          // Ground-truth label, source, generator, split, and identifying filename
          // never enter the model request. Opaque path filenames are mandatory.
          const result = await analyze({ path: resolve(root, item.path), mimeType: item.mimeType,
            id: item.id, metadata: item.media ?? {} });
          row = { ...item, decision: decisionOf(result), verdict: result.verdict,
            aiScore: result.aiScore ?? result.finalScore, confidence: result.confidence,
            elapsedMs: Date.now() - started, result };
        } catch (error) {
          row = { ...item, error: error instanceof Error ? error.message : String(error), elapsedMs: Date.now() - started };
        }
        rows.push(row);
        if (row.error) {
          consecutiveErrors = row.error === lastError ? consecutiveErrors + 1 : 1;
          lastError = row.error;
          if (consecutiveErrors >= 3) aborted = "Three consecutive identical errors; remaining requests not started";
        } else { consecutiveErrors = 0; lastError = null; }
        await appendFile(resolve(output, "predictions.jsonl"), JSON.stringify(row) + "\n");
        console.log(JSON.stringify({ completed: rows.length, selected: selected.length, id: row.id,
          decision: row.decision, error: row.error, elapsedMs: row.elapsedMs }));
      }
    }));
    plan.aborted = aborted;
    plan.sourceChangedDuringRun = (await sourceFingerprint()).digest !== plan.sourceFingerprint;
    plan.adapterBundleChangedDuringRun = hash(await readFile(bundle.path)) !== bundle.sha256;
  }
  const summary = { ...report(rows), plan };
  summary.selection = { selected: selected.length, attempted: rows.length, notAttempted: Math.max(0, selected.length - rows.length),
    completionRate: wilson(summary.overall.completed, selected.length) };
  await writeFile(resolve(output, "report.json"), JSON.stringify(summary, null, 2) + "\n");
  console.log(JSON.stringify({ output, ...summary.overall }, null, 2));
  if (summary.overall.errors || summary.selection.notAttempted || plan.adapterBundleChangedDuringRun) process.exitCode = 1;
}
