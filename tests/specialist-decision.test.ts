import { describe, expect, it } from "vitest";
import { aggregateSightengineEvidence } from "@/lib/analyzer/sightengine";
import { applySpecialistEvidence } from "@/lib/analyzer/specialist-decision";
import type { ScoreResult } from "@/lib/analyzer/types";

function base(verdict: ScoreResult["verdict"] = "No clear AI indicators"): ScoreResult {
  return { baseScore: 8, finalScore: 8, verdict, confidence: "Not calibrated",
    assessmentStatus: "complete", reviewRequired: false, evidenceLabel: "No reliable evidence of AI found",
    decisionReasons: ["Gemini finding"], adjustments: [] };
}
function evidence(scores: number[], complete = true) {
  return aggregateSightengineEvidence(scores.map((aiGenerated, index) => ({ positionSeconds: index * 0.5, aiGenerated })),
    { durationSeconds: scores.length * 0.5, technicalComplete: complete, declaredIntervalSeconds: 0.5 });
}

describe("specialist and Gemini evidence combination", () => {
  it("retains repeated specialist flags when Gemini misses them, without averaging scores", () => {
    const result = applySpecialistEvidence(base(), evidence([0.99, 0.99, 0.001, 0.99, 0.99]));
    expect(result.verdict).toBe("AI indicators detected");
    expect(result.assessmentStatus).toBe("complete");
    expect(result.reviewRequired).toBe(true);
    expect(result.confidence).toBe("Not calibrated");
    expect(result.finalScore).toBe(8);
    expect(result.decisionReasons.join(" ")).toContain("primary visual detector");
  });
  it("does not dismiss an isolated alert as a clear negative", () => {
    const result = applySpecialistEvidence(base(), evidence([0.001, 0.99, 0.001]));
    expect(result.verdict).toBe("Inconclusive");
    expect(result.reviewRequired).toBe(true);
  });
  it("does not clear a negative on a partial or failed provider scan", () => {
    expect(applySpecialistEvidence(base(), evidence([0.001, 0.001], false)).verdict).toBe("Inconclusive");
    expect(applySpecialistEvidence(base(), evidence([0.99, 0.99], false)).verdict).toBe("Inconclusive");
  });
  it("does not let a specialist no-hit result erase Gemini observations", () => {
    const result = applySpecialistEvidence(base("AI indicators detected"), evidence([0.001, 0.001]));
    expect(result.verdict).toBe("Inconclusive");
    expect(result.decisionReasons).toContain("Gemini finding");
    expect(result.reviewRequired).toBe(true);
  });
  it("requires a completed positive specialist scan before retaining a Gemini AI verdict", () => {
    expect(applySpecialistEvidence(base("AI indicators detected"), evidence([0.99, 0.001])).verdict).toBe("Inconclusive");
    expect(applySpecialistEvidence(base("AI indicators detected"), evidence([0.99, 0.99], false)).verdict).toBe("Inconclusive");
  });
  it("keeps isolated alerts unresolved even when both providers have positive findings", () => {
    const result = applySpecialistEvidence(base("AI indicators detected"), evidence([0.99, 0.99, 0.001, 0.99]));
    expect(result.verdict).toBe("AI indicators detected");
    expect(result.reviewRequired).toBe(true);
    expect(result.decisionReasons.join(" ")).toContain("isolated");
  });
  it("retains the authenticity limitation when both scans find no indicators", () => {
    const result = applySpecialistEvidence(base(), evidence([0.001, 0.001]));
    expect(result.verdict).toBe("No clear AI indicators");
    expect(result.decisionReasons.join(" ")).toContain("Brief AI inserts");
  });
  it("keeps trusted provenance and source disclosures separate from model votes", () => {
    for (const verdict of ["Verified AI provenance", "AI use disclosed"] as const) {
      const input = base(verdict);
      expect(applySpecialistEvidence(input, evidence([0.001, 0.001]))).toBe(input);
    }
  });
  it("preserves existing behavior when the optional provider is not in use", () => {
    const input = base();
    expect(applySpecialistEvidence(input, null)).toBe(input);
  });
  it("uses a completed specialist positive even when Gemini remains unresolved", () => {
    const input = { ...base("Inconclusive"), assessmentStatus: "conflicting" as const, reviewRequired: true };
    expect(applySpecialistEvidence(input, evidence([0.99, 0.99]))).toMatchObject({ verdict: "AI indicators detected", assessmentStatus: "complete" });
    for (const specialist of [evidence([0.001, 0.001]), evidence([0.001], false)]) {
      expect(applySpecialistEvidence(input, specialist).assessmentStatus).toBe("conflicting");
    }
  });
});
