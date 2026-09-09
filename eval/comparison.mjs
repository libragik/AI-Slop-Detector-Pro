import { metrics, wilson } from "./metrics.mjs";

const positive = row => row.label === "ai" || row.label === "mixed";
const completed = row => !row.error && ["ai", "not_ai", "abstain"].includes(row.decision);
const quantile = (values, fraction) => {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const position = fraction * (sorted.length - 1);
  const low = Math.floor(position);
  return sorted[low] + (sorted[Math.ceil(position)] - sorted[low]) * (position - low);
};

/** Describes observed pass status separately from successful scan responses. */
export function executionSummary(rows) {
  const latency = rows.map(row => row.elapsedMs).filter(value => Number.isFinite(value));
  const byPass = {};
  const failedScans = [];
  let scansWithoutPassTrace = 0;
  let scansWithInvalidCorroboration = 0;
  for (const row of rows) {
    const passes = row.result?.videoAnalysis?.inspection?.passes;
    if (!Array.isArray(passes) || passes.length === 0) {
      scansWithoutPassTrace++;
      continue;
    }
    if (passes.some(pass => pass.status === "failed")) failedScans.push(row);
    if (passes.some(pass => pass.status === "complete" && pass.validForCorroboration === false)) scansWithInvalidCorroboration++;
    for (const pass of passes) {
      const key = `${pass.kind}/${pass.mode}/${pass.model}`;
      const group = byPass[key] ??= { observed: 0, complete: 0, failed: 0, unknown: 0,
        completeInvalidForCorroboration: 0, reportedInputTokens: 0, reportedOutputTokens: 0,
        missingInputTokenCount: 0, missingOutputTokenCount: 0, elapsedMs: [] };
      group.observed++;
      group[["complete", "failed"].includes(pass.status) ? pass.status : "unknown"]++;
      if (pass.status === "complete" && pass.validForCorroboration === false) group.completeInvalidForCorroboration++;
      if (Number.isFinite(pass.inputTokens)) group.reportedInputTokens += pass.inputTokens;
      else group.missingInputTokenCount++;
      if (Number.isFinite(pass.outputTokens)) group.reportedOutputTokens += pass.outputTokens;
      else group.missingOutputTokenCount++;
      if (Number.isFinite(pass.elapsedMs)) group.elapsedMs.push(pass.elapsedMs);
    }
  }
  for (const group of Object.values(byPass)) {
    group.latencyMs = { measured: group.elapsedMs.length, median: quantile(group.elapsedMs, .5), p95: quantile(group.elapsedMs, .95) };
    delete group.elapsedMs;
  }
  const allAi = rows.filter(positive);
  const correct = rows.filter(row => completed(row) && (positive(row) ? row.decision === "ai" : row.decision === "not_ai"));
  return {
    selected: rows.length,
    endToEndAiRecall: wilson(allAi.filter(row => completed(row) && row.decision === "ai").length, allAi.length),
    endToEndCorrectDecisionRate: wilson(correct.length, rows.length),
    latencyMs: { measured: latency.length, median: quantile(latency, .5), p95: quantile(latency, .95), max: latency.length ? Math.max(...latency) : null },
    scansWithoutPassTrace, scansWithFailedPass: failedScans.length, scansWithInvalidCorroboration,
    failedPassScanMetrics: metrics(failedScans), byPass,
    caveat: "Pass summaries describe recorded attempts only. Missing traces are unavailable, not zero failures. Conditional adjudications not attempted are not failures. End-to-end rates count scan errors, missing attempts and abstentions as failures to make a correct decision."
  };
}

export function exactMcNemar(improved, regressed) {
  const total = improved + regressed;
  if (total === 0) return 1;
  let probability = 2 ** -total;
  let tail = probability;
  for (let k = 1; k <= Math.min(improved, regressed); k++) {
    probability *= (total - k + 1) / k;
    tail += probability;
  }
  return Math.min(1, 2 * tail);
}

/** Pairs identical source pixels. AI hit includes abstention/error as no hit. */
export function pairedComparison(before, after) {
  const lookup = new Map(after.map(row => [row.id, row]));
  if (lookup.size !== after.length || new Set(before.map(row => row.id)).size !== before.length || before.length !== after.length) throw new Error("Pair count or identity mismatch");
  const pairs = before.map(row => {
    const next = lookup.get(row.id);
    if (!next || next.sha256 !== row.sha256 || next.groupId !== row.groupId || next.label !== row.label) throw new Error("Paired source or truth mismatch");
    return [row, next];
  });
  const transitions = { ai: {}, nonAi: {} };
  let improved = 0;
  let regressed = 0;
  for (const [old, next] of pairs) {
    const key = `${completed(old) ? old.decision : "error"} -> ${completed(next) ? next.decision : "error"}`;
    const group = transitions[positive(old) ? "ai" : "nonAi"];
    group[key] = (group[key] ?? 0) + 1;
    if (!positive(old)) continue;
    const oldHit = completed(old) && old.decision === "ai";
    const newHit = completed(next) && next.decision === "ai";
    if (!oldHit && newHit) improved++;
    if (oldHit && !newHit) regressed++;
  }
  const aiPairs = pairs.filter(([row]) => positive(row));
  const grouped = new Map();
  for (const pair of aiPairs) grouped.set(pair[0].groupId, [...(grouped.get(pair[0].groupId) ?? []), pair]);
  const groups = [...grouped.values()];
  const differences = [];
  let randomState = 9183327;
  const random = () => { randomState = (Math.imul(1664525, randomState) + 1013904223) >>> 0; return randomState / 4294967296; };
  if (groups.length > 1) for (let i = 0; i < 10000; i++) {
    const draw = Array.from({ length: groups.length }, () => groups[Math.floor(random() * groups.length)]).flat();
    differences.push(draw.reduce((sum, [old, next]) => sum + Number(completed(next) && next.decision === "ai") - Number(completed(old) && old.decision === "ai"), 0) / draw.length);
  }
  return { transitions, ai: { count: aiPairs.length, sourceGroups: groups.length, improved, regressed,
    recallDifference: aiPairs.length ? (improved - regressed) / aiPairs.length : null,
    sourceGroupBootstrap95: differences.length ? [quantile(differences, .025), quantile(differences, .975)] : null,
    exactPairedTwoSidedP: exactMcNemar(improved, regressed),
    caveat: "Exact McNemar assumes independent source pairs; transformed derivatives require source-group analysis. Bootstrap interval is pointwise and can degenerate at boundaries. This is descriptive evaluation, not permission to tune on holdout." } };
}
