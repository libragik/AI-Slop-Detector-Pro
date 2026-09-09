import { describe, expect, it } from "vitest";
import { metrics, wilson, decisionOf, clusterIntervals } from "./metrics.mjs";

describe("evaluation metrics", () => {
  it("does not reward abstaining on every clip", () => {
    const result = metrics([{ label: "ai", decision: "abstain", groupId: "a" }, { label: "real", decision: "abstain", groupId: "b" }]);
    expect(result.aiRecall.estimate).toBe(0);
    expect(result.coverage.estimate).toBe(0);
    expect(result.committedAccuracy.estimate).toBeNull();
    expect(result.falseNegativeContamination.estimate).toBeNull();
  });
  it("tracks confidently missed AI among claimed negatives", () => {
    const result = metrics([{ label: "mixed", decision: "not_ai", confidence: "High", groupId: "a" },
      { label: "cgi", decision: "not_ai", confidence: "High", groupId: "b" },
      { label: "real", decision: "ai", confidence: "Low", groupId: "c" },
      { label: "ai", error: "timeout", groupId: "d" }]);
    expect(result.falseNegativeContamination.estimate).toBe(.5);
    expect(result.falsePositiveRate.estimate).toBe(.5);
    expect(result.highConfidenceErrorRate.estimate).toBe(.5);
    expect(result.completionRate.estimate).toBe(.75);
  });
  it("gives a nonzero upper uncertainty bound after zero errors", () => {
    expect(wilson(0, 10).interval95[1]).toBeGreaterThan(.25);
    expect(wilson(0, 0).interval95).toBeNull();
  });
  it("uses reproducible group bootstrap and rejects unknown verdicts", () => {
    const rows = [{ label: "ai", decision: "ai", groupId: "a" }, { label: "real", decision: "ai", groupId: "b" }];
    expect(clusterIntervals(rows, 100)).toEqual(clusterIntervals(rows, 100));
    expect(decisionOf({ verdict: "Probably Not AI" })).toBe("not_ai");
    expect(() => decisionOf({ verdict: "looks fine" })).toThrow();
  });
});
