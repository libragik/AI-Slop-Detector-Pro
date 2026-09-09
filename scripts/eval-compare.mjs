#!/usr/bin/env node
import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { parseArgs } from "node:util";
import { createHash } from "node:crypto";
import { decisionOf, report } from "../eval/metrics.mjs";
import { executionSummary, pairedComparison } from "../eval/comparison.mjs";

const { values } = parseArgs({ options: {
  before: { type: "string" }, after: { type: "string" },
  manifest: { type: "string", default: "eval/manifest.jsonl" },
  split: { type: "string", default: "holdout" }, output: { type: "string" },
  unseal: { type: "boolean", default: false }
} });
if (!values.before || !values.after || !values.output || !values.unseal) {
  throw new Error("Requires --before RUN_DIR --after RUN_DIR --output FILE --unseal. Only unseal after both runs finish and candidate selection is frozen.");
}
const hash = data => createHash("sha256").update(data).digest("hex");
const parseLines = data => data.trim().split("\n").filter(Boolean).map(line => JSON.parse(line));
const manifestBytes = await readFile(resolve(values.manifest));
const selected = parseLines(manifestBytes.toString()).filter(row => values.split === "all" || row.split === values.split);
if (!selected.length) throw new Error("Empty selected split");
const truthById = new Map(selected.map(row => [row.id, row]));
if (truthById.size !== selected.length) throw new Error("Duplicate manifest IDs");

async function loadRun(directory) {
  const predictionBytes = await readFile(resolve(directory, "predictions.jsonl"));
  const originalReport = JSON.parse(await readFile(resolve(directory, "report.json"), "utf8"));
  const plan = JSON.parse(await readFile(resolve(directory, "plan.json"), "utf8"));
  if (plan.manifestSha256 !== hash(manifestBytes) || plan.selected !== selected.length || plan.split !== values.split) throw new Error("Run plan does not match the full selected manifest");
  const seen = new Set();
  const attempted = parseLines(predictionBytes.toString()).map(row => {
    const truth = truthById.get(row.id);
    if (!truth || row.sha256 !== truth.sha256 || seen.has(row.id)) throw new Error("Prediction identity/hash mismatch");
    seen.add(row.id);
    return { ...row, ...truth, decision: row.error ? undefined : decisionOf(row.result ?? row) };
  });
  const allSelected = [...attempted, ...selected.filter(row => !seen.has(row.id)).map(row => ({ ...row, error: "not_attempted" }))];
  return { allSelected, summary: {
    directory, predictionSha256: hash(predictionBytes), plan,
    collection: { selected: selected.length, attempted: attempted.length, notAttempted: selected.length - attempted.length },
    originalRunSelection: originalReport.selection ?? null,
    metrics: report(attempted), execution: executionSummary(allSelected)
  } };
}

const before = await loadRun(values.before);
const after = await loadRun(values.after);
const comparison = {
  createdAt: new Date().toISOString(), manifestSha256: hash(manifestBytes), split: values.split,
  before: before.summary, after: after.summary,
  paired: pairedComparison(before.allSelected, after.allSelected),
  caveats: [
    "Candidate selection must be frozen before this report is generated; do not tune from these outcomes.",
    "Conditional class metrics exclude scan errors; execution rates include every selected source and count missing attempts and abstentions as failure to make a correct decision.",
    "Pass failures are separate from completed scan responses; baseline missing pass traces do not prove zero pass failures.",
    "Per-generator sample sizes are small; the corpus is author-labeled, publicly available and lacks independent camera provenance.",
    "Paired bootstrap is pointwise; test and interval do not establish broad deployment reliability or calibrated confidence."
  ]
};
await writeFile(resolve(values.output), JSON.stringify(comparison, null, 2) + "\n");
console.log(JSON.stringify({ output: resolve(values.output), selected: selected.length,
  before: comparison.before.metrics.overall.confusion, after: comparison.after.metrics.overall.confusion,
  pairedAi: comparison.paired.ai }, null, 2));
