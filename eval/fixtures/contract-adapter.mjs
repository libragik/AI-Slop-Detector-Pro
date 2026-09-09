/** Offline harness fixture; never use these outputs as detection evidence. */
export async function analyzeEvaluationVideo(input) {
  if (Object.keys(input).some(key => ["label", "generator", "split", "groundTruth", "sourceUrl"].includes(key))) {
    throw new Error("Ground truth leaked to adapter");
  }
  if (Object.keys(input.metadata).some(key => ["label", "generator", "split", "groundTruth", "sourceUrl"].includes(key))) {
    throw new Error("Ground truth leaked through metadata");
  }
  return { decision: "abstain", verdict: "Inconclusive", confidence: "Low", fixture: true };
}
