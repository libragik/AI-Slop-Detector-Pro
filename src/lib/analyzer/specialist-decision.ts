import type { ScoreResult } from "./types";
import type { SightengineEvidence } from "./sightengine-types";

/** Combine findings without averaging unrelated, uncalibrated model scores. */
export function applySpecialistEvidence(base: ScoreResult, specialist: SightengineEvidence | null): ScoreResult {
  if (!specialist) return base;
  // Credentials and explicit source declarations retain their own provenance semantics.
  if (base.verdict === "Verified AI provenance" || base.verdict === "AI use disclosed") return base;
  const positive = base.verdict === "AI indicators detected";
  const unresolvedStatus = base.assessmentStatus === "conflicting" ? "conflicting" : "limited";
  const negative = base.verdict === "No clear AI indicators";
  const complete = specialist.status === "complete" && specialist.coverage.complete;
  const sustained = complete && specialist.verdict === "persistent_ai_indicators" && specialist.persistentRuns.length > 0;
  const noHits = complete && specialist.verdict === "no_clear_indicators" && specialist.isolatedAlerts.length === 0;

  const result = (changes: Partial<ScoreResult>, reason: string): ScoreResult => ({
    ...base, ...changes, confidence: "Not calibrated",
    decisionReasons: [reason, ...(changes.decisionReasons ?? base.decisionReasons)],
    adjustments: [...base.adjustments, {
      source: "sightengine", rule: "specialist_primary_positive_v3",
      scoreBefore: base.finalScore, scoreAfter: base.finalScore, delta: 0,
      reason: "Repeated Sightengine findings determine the visual AI verdict. Gemini provides supporting review; its raw score is kept separate.",
    }],
  });

  if (sustained) {
    const count = specialist.persistentRuns.reduce((sum, run) => sum + run.sampleIndices.length, 0);
    const reason = `Sightengine detected repeated AI indicators in ${count} sampled frames across ${specialist.persistentRuns.length} stretch${specialist.persistentRuns.length === 1 ? "" : "es"} of this video.`;
    return result({
      verdict: "AI indicators detected", evidenceLabel: "AI indicators observed",
      assessmentStatus: "complete",
      reviewRequired: true,
      decisionReasons: [
        positive ? "Gemini also found AI indicators in this video."
          : negative ? "Gemini found no clear indicators in the same media. Sightengine is the primary visual detector, so this disagreement does not override its repeated AI findings."
            : "Gemini did not reach a settled assessment. Sightengine's completed visual scan determines this verdict; Gemini's review remains available below.",
        ...(specialist.isolatedAlerts.length ? ["Additional isolated frame alerts remain unresolved."] : []),
        "Repeated model flags are evidence to inspect, not verified origin or a confidence percentage.",
        "Sightengine can also flag camera footage or conventional CGI. This is a detector finding, not verified origin.",
      ],
    }, reason);
  }

  if (!noHits) {
    const reason = complete && specialist.isolatedAlerts.length
      ? "Sightengine flagged isolated frames. Those alerts remain unresolved and cannot support a clear negative result."
      : "The specialist scan could not establish complete evidence for this video.";
    return result({
      verdict: "Inconclusive",
      evidenceLabel: "Inconclusive",
      assessmentStatus: unresolvedStatus, reviewRequired: true,
    }, reason);
  }

  if (negative) {
    return result({ decisionReasons: [
      "This does not establish authenticity. Brief AI inserts between sampled frames and convincing generated footage can still be missed.",
    ] }, "The specialist scan and Gemini reviews found no clear AI indicators in the sampled media.");
  }
  return result({ verdict: "Inconclusive", evidenceLabel: "Inconclusive",
    assessmentStatus: positive ? "conflicting" : unresolvedStatus, reviewRequired: true },
    "Sightengine did not flag its sampled frames. Gemini's findings remain available, but the combined evidence does not support a settled AI assessment.");
}
