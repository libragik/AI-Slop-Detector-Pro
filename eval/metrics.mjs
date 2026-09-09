/** Evaluation metrics treat abstention as neither a correct negative nor a hit. */
export function wilson(successes, total, z = 1.959963984540054) {
  if (total === 0) return { numerator: successes, denominator: total, estimate: null, interval95: null };
  const p = successes / total;
  const d = 1 + z * z / total;
  const center = (p + z * z / (2 * total)) / d;
  const half = z * Math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / d;
  return { numerator: successes, denominator: total, estimate: p,
    interval95: [Math.max(0, center - half), Math.min(1, center + half)] };
}

export function decisionOf(result) {
  if (result.decision && ["ai", "not_ai", "abstain"].includes(result.decision)) return result.decision;
  const value = String(result.verdict ?? "").toLowerCase();
  if (["probably ai", "likely ai", "likely synthetic", "ai detected", "ai evidence found"].includes(value)) return "ai";
  if (["probably not ai", "unlikely ai", "unlikely to be ai", "likely authentic"].includes(value)) return "not_ai";
  if (["inconclusive", "uncertain", "not enough evidence", "no reliable evidence of ai found"].includes(value)) return "abstain";
  throw new Error(`Unknown verdict contract: ${String(result.verdict)}. Adapter must return decision: ai | not_ai | abstain.`);
}

export function metrics(rows) {
  const complete = rows.filter(r => !r.error && ["ai", "not_ai", "abstain"].includes(r.decision));
  const positive = complete.filter(r => r.label === "ai" || r.label === "mixed");
  const negative = complete.filter(r => r.label === "real" || r.label === "cgi");
  const tp = positive.filter(r => r.decision === "ai").length;
  const fn = positive.filter(r => r.decision === "not_ai").length;
  const fp = negative.filter(r => r.decision === "ai").length;
  const tn = negative.filter(r => r.decision === "not_ai").length;
  const abstained = complete.filter(r => r.decision === "abstain").length;
  const high = complete.filter(r => r.decision !== "abstain" && String(r.confidence).toLowerCase() === "high");
  const highWrong = high.filter(r => ((r.label === "ai" || r.label === "mixed") && r.decision === "not_ai") ||
    ((r.label === "real" || r.label === "cgi") && r.decision === "ai")).length;
  return { attempted: rows.length, completed: complete.length, errors: rows.length - complete.length,
    sourceGroups: new Set(rows.map(r => r.groupId)).size,
    confusion: { truePositive: tp, falseNegative: fn, falsePositive: fp, trueNegative: tn,
      abstainedAi: positive.length - tp - fn, abstainedNonAi: negative.length - fp - tn },
    aiRecall: wilson(tp, positive.length), falsePositiveRate: wilson(fp, negative.length),
    aiDetectionFailureRate: wilson(positive.length - tp, positive.length),
    falseNegativeRate: wilson(fn, positive.length),
    falseNegativeContamination: wilson(fn, fn + tn),
    aiPrecision: wilson(tp, tp + fp), abstentionRate: wilson(abstained, complete.length),
    coverage: wilson(complete.length - abstained, complete.length),
    committedAccuracy: wilson(tp + tn, tp + tn + fp + fn),
    highConfidenceErrorRate: wilson(highWrong, high.length),
    completionRate: wilson(complete.length, rows.length) };
}

function seededRandom(seed = 5149304) {
  let state = seed >>> 0;
  return () => { state = (Math.imul(1664525, state) + 1013904223) >>> 0; return state / 4294967296; };
}

/** Cluster bootstrap resamples source groups, keeping derivatives together. */
export function clusterIntervals(rows, replicates = 1000) {
  const grouped = new Map();
  for (const row of rows) grouped.set(row.groupId, [...(grouped.get(row.groupId) ?? []), row]);
  const groups = [...grouped.values()];
  if (groups.length < 2) return { method: "source-group bootstrap", replicates, intervals95: null };
  const random = seededRandom();
  const samples = {};
  for (let i = 0; i < replicates; i++) {
    const draw = Array.from({ length: groups.length }, () => groups[Math.floor(random() * groups.length)]).flat();
    for (const [key, value] of Object.entries(metrics(draw))) {
      if (typeof value === "object" && value && typeof value.estimate === "number") (samples[key] ??= []).push(value.estimate);
    }
  }
  const intervals95 = Object.fromEntries(Object.entries(samples).map(([key, values]) => {
    values.sort((a, b) => a - b);
    return [key, { interval: [values[Math.floor(values.length * .025)], values[Math.min(values.length - 1, Math.floor(values.length * .975))]], validReplicates: values.length }];
  }));
  return { method: "source-group percentile bootstrap; pointwise; undefined ratios omitted", replicates, intervals95 };
}

export function report(rows) {
  const by = field => Object.fromEntries([...new Set(rows.map(r => String(r[field] ?? "unknown")))].sort().map(value =>
    [value, metrics(rows.filter(r => String(r[field] ?? "unknown") === value))]));
  return { generatedAt: new Date().toISOString(), overall: metrics(rows),
    sourceGroupUncertainty: clusterIntervals(rows),
    byLabel: by("label"), byGenerator: by("generator"), bySplit: by("split"), byDataset: by("dataset"),
    byTransformation: by("transformation"), byPlatform: by("platform"),
    caveats: ["Wilson intervals assume independent rows; use source-group bootstrap for transformed or paired clips.",
      "Small samples and zero observed errors do not establish zero population error.",
      "Percentile bootstrap can degenerate at zero or one; inspect Wilson intervals for independent original clips at those boundaries.",
      "Group independence is only as reliable as dataset source identifiers; per-camera source IDs are missing for GenBuster clips.",
      "False-negative contamination is measured at this corpus prevalence; it is not a deployment probability.",
      "Errors are reported separately and excluded from class metrics; coverage and completion must be assessed together.",
      "An abstention on an AI video is a recall miss but not a confidently negative classification.",
      "Scores are uncalibrated; this report does not convert model scores into probabilities."] };
}
