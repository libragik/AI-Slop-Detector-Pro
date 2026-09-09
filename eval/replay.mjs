/** Reconstruct precisely the inputs passed by pipeline.buildResult, without rerunning media or models. */
export function scoringInputs(result) {
  if (!result?.videoAnalysis || !result.provenance) throw new Error("Saved result lacks replayable video analysis or provenance");
  return {
    video: result.videoAnalysis,
    provenance: result.provenance,
    metadata: result.youtube?.metadata,
    comments: result.youtube?.comments,
    disclosure: result.socialContext ? {
      disclosed: result.socialContext.disclosureReasons.length > 0,
      reasons: result.socialContext.disclosureReasons,
    } : null,
  };
}

export function policyDecision(score) {
  if (score.verdict === "Inconclusive") return "abstain";
  if (score.verdict === "No clear AI indicators") return "not_ai";
  if (["AI indicators detected", "AI use disclosed", "Verified AI provenance"].includes(score.verdict)) return "ai";
  throw new Error(`Unexpected replay scorer verdict: ${score.verdict}`);
}

export function replayRow(row, aggregateScore, provenance) {
  if (row.error) return { row, changes: null };
  const score = aggregateScore(structuredClone(scoringInputs(row.result)));
  const decision = policyDecision(score);
  const changedScoreFields = Object.keys(score).filter(key => JSON.stringify(score[key]) !== JSON.stringify(row.result[key]));
  const changes = {
    id: row.id, originalDecision: row.decision, replayedDecision: decision,
    decisionChanged: row.decision !== decision,
    changedScoreFields,
  };
  return {
    row: {
      ...row, decision, verdict: score.verdict, aiScore: score.finalScore, confidence: score.confidence,
      result: {
        ...row.result, ...score, aiScore: score.finalScore, decision,
        // Original model/runtime identity remains intact; only this additional
        // receipt identifies the separately replayed decision policy.
        scoreReplay: provenance,
      },
    }, changes,
  };
}
