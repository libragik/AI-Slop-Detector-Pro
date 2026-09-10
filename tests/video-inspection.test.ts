import { describe, expect, it, vi } from "vitest";
import { inspectVideo, reviewWindows, timestampSeconds, type VideoPassRequest, type VideoPassResult } from "@/lib/analyzer/video-inspection";
import type { VideoAnalysis } from "@/lib/analyzer/types";
import { aggregateScore } from "@/lib/analyzer/scoring";

const config = { model: "test-model", reviewModel: "test-reviewer", sweepFps: 2, reviewFps: 6, reviewMode: "agentic" as const };
const input = { uri: "test://clip", durationSeconds: 10, width: 1280, height: 720, hasAudio: false };
const negative = (overrides: Partial<VideoAnalysis> = {}): VideoAnalysis => ({
  aiLikelihood: 5, visualClassification: "likely_not_ai_generated", visualAssessment: "likely_authentic",
  audioAssessment: "inconclusive", identityManipulation: "none_detected", contentType: "camera_footage",
  summary: "No reproducible visual generation indicators observed.", suspiciousMoments: [], evidenceAgainstAi: [],
  alternativeExplanations: [], limitations: [], agenticProcessingObserved: false,
  evidenceSufficiency: "sufficient", qualityIssues: [], ...overrides,
});
const positive = () => negative({ aiLikelihood: 85, visualClassification: "likely_ai_generated", visualAssessment: "generated",
  suspiciousMoments: [{ timestamp: "00:04.25", category: "temporal", severity: "high", observation: "The same held object changes shape across adjoining frames." }] });
const result = (analysis: VideoAnalysis, request: VideoPassRequest): VideoPassResult => ({ analysis, receipt: {
  kind: request.kind, mode: request.mode, model: request.model, fps: request.mode === "static" ? request.fps : null,
  status: "complete", elapsedMs: 1, aiLikelihood: analysis.aiLikelihood, classification: analysis.visualClassification,
  summary: analysis.summary, inputTokens: 10, outputTokens: 5, intervals: [{ startSeconds: 0, endSeconds: 10 }],
} });

describe("deliberate video inspection", () => {
  it("runs an independent sweep and review without passing the first opinion into the reviewer", async () => {
    const requests: VideoPassRequest[] = [];
    const video = await inspectVideo(input, async (_, request) => { requests.push(request); return result(negative(), request); }, config);
    expect(requests).toHaveLength(2);
    expect(requests[0]).toMatchObject({ kind: "sweep", mode: "static", fps: 2 });
    expect(requests[1].prompt).not.toContain("No reproducible");
    expect(video.inspection).toMatchObject({ reviewAgreement: "agree", audioCoverage: "no_audio", temporalCoverage: "adequate" });
  });
  it("requires a further inspection when the independent passes disagree", async () => {
    const requests: VideoPassRequest[] = [];
    const video = await inspectVideo(input, async (_, request) => {
      requests.push(request); return result(request.kind === "sweep" ? negative() : positive(), request);
    }, config);
    expect(requests).toHaveLength(3);
    expect(requests[2]).toMatchObject({ kind: "adjudication", mode: "static", windows: [{ startSeconds: 2.25, endSeconds: 6.25 }] });
    expect(video.inspection?.reviewAgreement).toBe("resolved");
  });
  it("preserves agreeing readable AI observations despite the g38 compression and no-audio quality notes", async () => {
    // Reproduces the live GenBuster luma contract run: both reviewers cited
    // matching morphing objects but quality prose previously invalidated all
    // three passes and incorrectly turned agreement into a conflict.
    const run = vi.fn(async (_, request: VideoPassRequest) => result({
      ...positive(), aiLikelihood: request.kind === "sweep" ? 75 : 98,
      suspiciousMoments: [{ timestamp: "00:02.500", category: "temporal", severity: "high",
        observation: "The small hair pin morphs into an extended horizontal band spanning the back of the head." }],
      qualityIssues: request.kind === "sweep" ? ["Moderate video compression."] : ["No audio stream present in the container."],
    }, request));
    const video = await inspectVideo({ ...input, durationSeconds: 5.041667, width: 1024, height: 1024 }, run, config);
    expect(run).toHaveBeenCalledTimes(2);
    expect(video.inspection).toMatchObject({ reviewAgreement: "agree", visualCoverage: "adequate", audioCoverage: "no_audio" });
    expect(video.inspection?.passes.map((pass) => pass.validForCorroboration)).toEqual([true, true]);
    expect(video.inspection?.passes.every((pass) => pass.consistencyIssues?.length === 0)).toBe(true);
    expect(video.qualityIssues).toEqual(["Moderate video compression.", "No audio stream present in the container."]);
    expect(video.inspection?.issues.join(" ")).not.toContain("insufficient");
    expect(aggregateScore({ video })).toMatchObject({ verdict: "AI indicators detected", assessmentStatus: "complete", reviewRequired: false });
  });
  it("treats measured absence of audio as neutral for a sufficient positive visual assessment", async () => {
    const video = await inspectVideo(input, async (_, request) => result(positive(), request), config);
    expect(video.inspection).toMatchObject({ reviewAgreement: "agree", audioCoverage: "no_audio", visualCoverage: "adequate" });
    expect(aggregateScore({ video })).toMatchObject({ verdict: "AI indicators detected", assessmentStatus: "complete" });
  });
  it.each([
    { evidenceSufficiency: "insufficient" },
    { aiLikelihood: 0 },
    { suspiciousMoments: [{ timestamp: "99:99", category: "temporal", severity: "high", observation: "A purported object morph." }] },
    { audioAssessment: "synthetic" },
  ] satisfies Partial<VideoAnalysis>[])("does not let quality notes excuse a defective positive reading: %j", async (defect) => {
    const run = vi.fn(async (_, request: VideoPassRequest) => result({
      ...positive(), qualityIssues: ["Moderate video compression."], ...defect,
    }, request));
    const video = await inspectVideo(input, run, config);
    expect(run).toHaveBeenCalledTimes(3);
    expect(video.inspection?.passes.every((pass) => pass.validForCorroboration === false)).toBe(true);
    expect(aggregateScore({ video })).toMatchObject({ verdict: "Inconclusive", reviewRequired: true });
  });
  it("keeps readable negative assessments when reviewers report informational quality notes", async () => {
    const run = vi.fn(async (_, request: VideoPassRequest) => result(negative({
      qualityIssues: request.kind === "review" ? ["Moderate video compression."] : [],
    }), request));
    const video = await inspectVideo(input, run, config);
    expect(run).toHaveBeenCalledTimes(2);
    expect(video.inspection).toMatchObject({ reviewAgreement: "agree", visualCoverage: "adequate" });
    expect(video.qualityIssues).toContain("Moderate video compression.");
    expect(aggregateScore({ video })).toMatchObject({ verdict: "No clear AI indicators", assessmentStatus: "complete" });
  });
  it("retains corroborated TTS observations while the deployment guard abstains on audio origin alone", async () => {
    const run = vi.fn(async (_, request: VideoPassRequest) => result(negative({
      aiLikelihood: request.kind === "sweep" ? 32 : 25, audioAssessment: "synthetic",
      suspiciousMoments: [{ timestamp: "00:00.0", category: "audio", severity: "medium",
        observation: "Synthetic narration with characteristic neural cadence and flat acoustic resonance." }],
    }), request));
    const video = await inspectVideo({ ...input, hasAudio: true, durationSeconds: 6.76 }, run, config);
    expect(run).toHaveBeenCalledTimes(2);
    expect(video.inspection).toMatchObject({ reviewAgreement: "agree", audioCoverage: "adequate" });
    expect(video.audioAssessment).toBe("synthetic");
    expect(video.suspiciousMoments.some((moment) => moment.category === "audio")).toBe(true);
    expect(aggregateScore({ video })).toMatchObject({ verdict: "Inconclusive", assessmentStatus: "limited", reviewRequired: true, finalScore: 32, confidence: "Not calibrated" });
  });
  it("does not collapse different suspected modalities into agreement", async () => {
    const run = vi.fn(async (_, request: VideoPassRequest) => result(request.kind === "review"
      ? negative({ aiLikelihood: 85, audioAssessment: "synthetic", visualClassification: "mixed_or_ai_edited" }) : positive(), request));
    await inspectVideo({ ...input, hasAudio: true }, run, config);
    expect(run).toHaveBeenCalledTimes(3);
  });
  it("retains disagreement when adjudication fails", async () => {
    const video = await inspectVideo(input, async (_, request) => {
      if (request.kind === "adjudication") throw new Error("failure");
      return result(request.kind === "sweep" ? negative() : positive(), request);
    }, config);
    expect(video.inspection?.reviewAgreement).toBe("disagree");
    expect(video.inspection?.passes.at(-1)?.status).toBe("failed");
  });
  it("cannot use an unreadable second report to corroborate a negative", async () => {
    const video = await inspectVideo(input, async (_, request) => {
      if (request.kind === "adjudication") throw new Error("No replacement review available");
      return result(negative(request.kind === "review"
        ? { evidenceSufficiency: "insufficient", qualityIssues: ["No usable visual detail"] } : {}), request);
    }, config);
    expect(video.inspection?.reviewAgreement).toBe("disagree");
    expect(video.inspection?.visualCoverage).toBe("limited");
    expect(video.qualityIssues).toContain("No usable visual detail");
    expect(aggregateScore({ video })).toMatchObject({ verdict: "Inconclusive", reviewRequired: true });
  });
  it("retains invalid observation status even after removing unsafe timestamps", async () => {
    const video = await inspectVideo(input, async (_, request) => result(negative({ suspiciousMoments: [{
      timestamp: "99:99", observation: "Unverified observation", severity: "high", category: "temporal",
    }] }), request), config);
    expect(video.suspiciousMoments).toEqual([]);
    expect(video.inspection?.invalidObservations).toBe(true);
  });
  it("records failed review and does not claim full coverage without a completed sweep", async () => {
    const video = await inspectVideo(input, async (_, request) => {
      if (request.kind === "sweep") throw new Error("failure");
      return result(negative(), request);
    }, config);
    expect(video.inspection).toMatchObject({ reviewAgreement: "not_available", temporalCoverage: "limited" });
  });
  it("fails when neither pass completed", async () => {
    await expect(inspectVideo(input, async () => { throw new Error("no provider"); }, config)).rejects.toThrow("either review pass");
  });

  it.each([
    { aiLikelihood: 95 },
    { visualAssessment: "generated" },
    { suspiciousMoments: positive().suspiciousMoments },
    { suspiciousMoments: [{ timestamp: "01:39", category: "temporal", severity: "high", observation: "The object disappears and the hand morphs." }] },
    { evidenceSufficiency: "insufficient" },
  ] satisfies Partial<VideoAnalysis>[])("does not discard a defective nonselected review into a clean negative: %j", async (defect) => {
    const review = negative(defect);
    const run = vi.fn(async (_, request: VideoPassRequest) => {
      if (request.kind === "adjudication") throw new Error("Adjudication unavailable");
      return result(request.kind === "sweep" ? negative() : review, request);
    });
    const video = await inspectVideo(input, run, config);
    expect(run).toHaveBeenCalledTimes(3);
    expect(aggregateScore({ video })).toMatchObject({ verdict: "Inconclusive", reviewRequired: true });
    const receipt = video.inspection?.passes.find((pass) => pass.kind === "review");
    expect(receipt?.rawAnalysis).toEqual(review);
    expect(receipt?.validForCorroboration).toBe(false);
    expect(receipt?.consistencyIssues?.length).toBeGreaterThan(0);
  });

  it("does not let one clean adjudication launder two defective original reports", async () => {
    const video = await inspectVideo(input, async (_, request) => result(
      request.kind === "adjudication" ? negative() : negative({ aiLikelihood: 95 }), request), config);
    expect(video.inspection?.reviewAgreement).toBe("disagree");
    expect(video.inspection?.passes.map((pass) => pass.validForCorroboration)).toEqual([false, false, true]);
    expect(aggregateScore({ video })).toMatchObject({ verdict: "Inconclusive", reviewRequired: true });
  });

  it("requires the adjudication itself to be internally consistent", async () => {
    const video = await inspectVideo(input, async (_, request) => result(
      request.kind === "review" ? positive() : negative(request.kind === "adjudication" ? { aiLikelihood: 95 } : {}), request), config);
    expect(video.inspection?.reviewAgreement).toBe("disagree");
    expect(video.inspection?.passes.at(-1)?.validForCorroboration).toBe(false);
    expect(aggregateScore({ video }).verdict).toBe("Inconclusive");
  });

  it("requires a valid original corroborator, not a defective original with the same category", async () => {
    const video = await inspectVideo(input, async (_, request) => result(
      request.kind === "sweep" ? positive() : negative(request.kind === "review" ? { aiLikelihood: 95 } : {}), request), config);
    expect(video.inspection?.reviewAgreement).toBe("disagree");
    expect(aggregateScore({ video }).verdict).toBe("Inconclusive");
  });

  it("can resolve a defective review with two valid readings while preserving its exact rejected evidence", async () => {
    const rejected = negative({ suspiciousMoments: [{ timestamp: "01:39", category: "temporal", severity: "high", observation: "A claimed anomaly outside this ten-second clip." }] });
    const requests: VideoPassRequest[] = [];
    const video = await inspectVideo(input, async (_, request) => {
      requests.push(request);
      return result(request.kind === "review" ? rejected : negative(), request);
    }, config);
    expect(requests).toHaveLength(3);
    expect(requests[2].prompt).toContain("01:39");
    expect(video.inspection?.reviewAgreement).toBe("resolved");
    expect(video.inspection?.passes[1].rawAnalysis).toEqual(rejected);
    expect(video.inspection?.passes[1].validForCorroboration).toBe(false);
    expect(video.inspection?.issues.join(" ")).toContain("invalid timestamp");
    expect(aggregateScore({ video })).toMatchObject({ verdict: "No clear AI indicators", assessmentStatus: "complete", confidence: "Not calibrated" });
  });

  it("allows agentic mode for sweep and recognizes agentic sweep as adequate temporal coverage", async () => {
    const agenticConfig = { ...config, sweepMode: "agentic" as const };
    const requests: VideoPassRequest[] = [];
    const video = await inspectVideo(input, async (_, request) => { requests.push(request); return result(negative(), request); }, agenticConfig);
    expect(requests).toHaveLength(2);
    expect(requests[0]).toMatchObject({ kind: "sweep", mode: "agentic" });
    expect(video.inspection).toMatchObject({ reviewAgreement: "agree", temporalCoverage: "adequate" });
  });
});

describe("evidence timestamp windows", () => {
  it("accepts fractional timestamps and rejects invalid seconds", () => {
    expect(timestampSeconds("00:04.25")).toBe(4.25);
    expect(timestampSeconds("01:02:03.5")).toBe(3723.5);
    expect(timestampSeconds("00:99")).toBeNull();
  });
  it("clips and deduplicates windows and ignores out-of-range observations", () => {
    expect(reviewWindows([positive(), positive()], 5)).toEqual([{ startSeconds: 2.25, endSeconds: 5 }]);
    expect(reviewWindows([positive()], 2)).toEqual([]);
  });
});
