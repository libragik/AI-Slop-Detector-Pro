#!/usr/bin/env node
/** Report uncalibrated specialist scores; never select a threshold on holdout. */
import { readFile, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { parseArgs } from "node:util";
import { report } from "../eval/metrics.mjs";

const { values } = parseArgs({ options: {
  input: { type: "string" }, output: { type: "string" },
  manifest: { type: "string", default: "eval/manifest.jsonl" },
  threshold: { type: "string" }, "development-fpr": { type: "string" },
} });
if (!values.input || (values.threshold === undefined) === (values["development-fpr"] === undefined)) {
  throw new Error("Provide --input and exactly one of --threshold or --development-fpr");
}
const inputBytes = await readFile(values.input);
const rows = inputBytes.toString().trim().split("\n").map(JSON.parse);
const manifest = new Map((await readFile(values.manifest, "utf8")).trim().split("\n").map(line => {
  const row = JSON.parse(line); return [row.id, row];
}));
if (new Set(rows.map(row => row.id)).size !== rows.length) throw new Error("Duplicate predictions");
for (const row of rows) {
  const truth = manifest.get(row.id);
  if (!truth || truth.sha256 !== row.sha256 || row.error || !Number.isFinite(row.syntheticScore)) {
    throw new Error(`Incomplete or mismatched prediction: ${row.id}`);
  }
  Object.assign(row, truth);
}
const positive = row => ["ai", "mixed"].includes(row.label);
function auc(sample) {
  const ordered = [...sample].sort((a, b) => a.syntheticScore - b.syntheticScore);
  const nPositive = ordered.filter(positive).length, nNegative = ordered.length - nPositive;
  if (!nPositive || !nNegative) return null;
  let correct = 0, lowerNegative = 0;
  for (let start = 0; start < ordered.length;) {
    let end = start + 1;
    while (end < ordered.length && ordered[end].syntheticScore === ordered[start].syntheticScore) end++;
    const positives = ordered.slice(start, end).filter(positive).length, negatives = end - start - positives;
    correct += positives * (lowerNegative + negatives / 2);
    lowerNegative += negatives;
    start = end;
  }
  return correct / (nPositive * nNegative);
}
let threshold = Number(values.threshold), selection = "externally supplied; no threshold fitting in this report";
if (values["development-fpr"] !== undefined) {
  if (rows.some(row => row.split !== "development")) throw new Error("Threshold selection is restricted to development predictions");
  const target = Number(values["development-fpr"]);
  if (!Number.isFinite(target) || target < 0 || target >= 1) throw new Error("Development FPR target must be in [0,1)");
  const negatives = rows.filter(row => !positive(row)).map(row => row.syntheticScore).sort((a, b) => b - a);
  if (!negatives.length) throw new Error("Threshold selection needs development negatives");
  threshold = negatives[Math.floor(target * negatives.length)];
  selection = `chosen on development negatives for observed FPR <= ${target}; exploratory, not validated`;
}
if (!Number.isFinite(threshold)) throw new Error("Threshold must be finite");
const groups = new Map();
for (const row of rows) groups.set(row.groupId, [...(groups.get(row.groupId) ?? []), row]);
const units = [...groups.values()];
let seed = 1937303;
const random = () => { seed = (Math.imul(1664525, seed) + 1013904223) >>> 0; return seed / 4294967296; };
const samples = [];
for (let index = 0; index < 1000; index++) {
  const value = auc(Array.from({ length: units.length }, () => units[Math.floor(random() * units.length)]).flat());
  if (value !== null) samples.push(value);
}
samples.sort((a, b) => a - b);
const summary = { input: values.input, inputSha256: createHash("sha256").update(inputBytes).digest("hex"),
  threshold, decisionRule: "syntheticScore > threshold", thresholdSelection: selection,
  scoreIsProbability: false, auroc: { estimate: auc(rows),
    interval95: samples.length ? [samples[Math.floor(samples.length * .025)], samples[Math.floor(samples.length * .975)]] : null,
    method: "source-group percentile bootstrap", validReplicates: samples.length },
  ...report(rows.map(row => ({ ...row, decision: row.syntheticScore > threshold ? "ai" : "not_ai" }))) };
if (values.output) await writeFile(values.output, JSON.stringify(summary, null, 2) + "\n");
console.log(JSON.stringify({ output: values.output, auroc: summary.auroc, threshold, aiRecall: summary.overall.aiRecall,
  falsePositiveRate: summary.overall.falsePositiveRate, sourceGroups: units.length }, null, 2));
