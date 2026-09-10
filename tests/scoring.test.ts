import { describe, expect, it } from "vitest";

import { aggregateScore, type ScoreInputs } from "@/lib/analyzer/scoring";
import type { VideoAnalysis, VideoInspection } from "@/lib/analyzer/types";

const inspection = (overrides: Partial<VideoInspection> = {}): VideoInspection => ({
  visualCoverage: "adequate",
  temporalCoverage: "adequate",
  audioCoverage: "adequate",
  issues: [],
  reviewAgreement: "agree",
  strategy: "sweep_and_review",
  coverageBasis: "requested_sampling_and_model_report",
  durationSeconds: 20,
  passes: ["sweep", "review"].map((kind) => ({
    kind: kind as "sweep" | "review",
    mode: kind === "sweep" ? "static" as const : "agentic" as const,
    model: "test-model",
    fps: kind === "sweep" ? 4 : null,
    status: "complete" as const,
    elapsedMs: 1,
    aiLikelihood: 5,
    classification: "likely_not_ai_generated" as const,
    summary: "No clear indicators were observed.",
    inputTokens: 10,
    outputTokens: 10,
    intervals: [{ startSeconds: 0, endSeconds: 20 }],
  })),
  ...overrides,
});

const video = (overrides: Partial<VideoAnalysis> = {}): VideoAnalysis => ({
  aiLikelihood: 5,
  visualClassification: "likely_not_ai_generated",
  visualAssessment: "likely_authentic",
  audioAssessment: "likely_recorded",
  identityManipulation: "none_detected",
  contentType: "camera_footage",
  summary: "No clear generative AI indicators were observed in the inspected media.",
  suspiciousMoments: [],
  evidenceAgainstAi: ["Objects remain consistent over the inspected timeline."],
  alternativeExplanations: [],
  limitations: ["An artifact-free AI video may be indistinguishable from camera footage."],
  agenticProcessingObserved: true,
  evidenceSufficiency: "sufficient",
  inspection: inspection(),
  ...overrides,
});

const generated = (overrides: Partial<VideoAnalysis> = {}): VideoAnalysis => video({
  aiLikelihood: 85,
  visualClassification: "likely_ai_generated",
  visualAssessment: "generated",
  suspiciousMoments: [{ timestamp: "00:05", category: "temporal", severity: "high", observation: "The subject merges into an unrelated object continuously across consecutive frames." }],
  ...overrides,
});

const score = (inputVideo: VideoAnalysis, overrides: Omit<ScoreInputs, "video"> = {}) =>
  aggregateScore({ video: inputVideo, ...overrides });

const comments = (overrides: Partial<NonNullable<ScoreInputs["comments"]>> = {}): NonNullable<ScoreInputs["comments"]> => ({
  status: "complete",
  sampleSize: 100,
  commentsClaimingAi: 0,
  commentsClaimingReal: 0,
  creatorAdmissionFound: false,
  ...overrides,
});

describe("evidence-driven assessment", () => {
  it("never turns the original low-score inconclusive failure into a confident negative", () => {
    expect(score(video({ aiLikelihood: 5, visualClassification: "inconclusive", inspection: undefined, evidenceSufficiency: undefined }))).toMatchObject({
      verdict: "Inconclusive", confidence: "Not calibrated", reviewRequired: true, assessmentStatus: "limited",
    });
  });

  it("keeps a supported negative observational and never authenticates the clip", () => {
    const result = score(video());
    expect(result).toMatchObject({
      verdict: "No clear AI indicators", confidence: "Not calibrated", reviewRequired: false,
      assessmentStatus: "complete", baseScore: 5, finalScore: 5,
    });
    expect(result.decisionReasons.join(" ")).toContain("does not establish that the clip is authentic");
  });

  it.each(["animation", "cgi"] as const)("does not equate conventional %s with generative AI", (contentType) => {
    expect(score(video({ contentType }))).toMatchObject({ verdict: "No clear AI indicators", confidence: "Not calibrated" });
  });

  it.each([0, 100, NaN, Infinity, 12.5])("abstains on invalid raw evidence value %s", (aiLikelihood) => {
    const result = score(video({ aiLikelihood }));
    expect(result).toMatchObject({ verdict: "Inconclusive", confidence: "Not calibrated", assessmentStatus: "conflicting" });
    expect(Number.isFinite(result.finalScore)).toBe(true);
  });

  it.each([
    { visualClassification: "likely_ai_generated", visualAssessment: "generated" },
    { visualClassification: "mixed_or_ai_edited", visualAssessment: "edited" },
    { audioAssessment: "synthetic" },
    { identityManipulation: "face_swap" },
  ] satisfies Partial<VideoAnalysis>[])("abstains when positive modality claims lack cited evidence: %j", (overrides) => {
    expect(score(video({ ...overrides, aiLikelihood: 5 }))).toMatchObject({
      verdict: "Inconclusive", confidence: "Not calibrated", reviewRequired: true, assessmentStatus: "limited",
    });
  });

  it("abstains when an extreme high score contradicts consistent negative categories", () => {
    expect(score(video({ aiLikelihood: 95 }))).toMatchObject({ verdict: "Inconclusive", assessmentStatus: "conflicting" });
  });

  it("does not clear a clip whose own report cites substantial suspicious observations", () => {
    expect(score(video({ suspiciousMoments: generated().suspiciousMoments }))).toMatchObject({
      verdict: "Inconclusive", assessmentStatus: "conflicting", reviewRequired: true,
    });
  });

  it("uses a grounded visual indicator without inventing calibrated confidence", () => {
    expect(score(generated())).toMatchObject({
      verdict: "AI indicators detected", confidence: "Not calibrated", assessmentStatus: "complete",
      evidenceLabel: "AI indicators observed", baseScore: 85, finalScore: 85,
    });
  });

  it("accepts subsecond citations returned by real video inspection", () => {
    expect(score(generated({
      suspiciousMoments: [{ timestamp: "00:02.50", category: "temporal", severity: "high", observation: "The accessory morphs across adjacent frames." }],
    }))).toMatchObject({ verdict: "AI indicators detected", assessmentStatus: "complete" });
  });

  it("grounds positive verdict on diffusion fluid physics anomalies", () => {
    expect(score(generated({
      suspiciousMoments: [{ timestamp: "00:03.20", category: "physics", severity: "high", observation: "The pouring liquid stream violates volume conservation and surface tension." }],
    }))).toMatchObject({ verdict: "AI indicators detected", assessmentStatus: "complete", evidenceLabel: "AI indicators observed" });
  });

  it("retains supported audio-only observations without using them alone to decide AI origin", () => {
    const result = score(video({
      aiLikelihood: 75,
      audioAssessment: "synthetic",
      suspiciousMoments: [{ timestamp: "00:02", category: "audio", severity: "high", observation: "The voice contains repeatable synthesis discontinuities at phoneme boundaries." }],
    }));
    expect(result).toMatchObject({ verdict: "Inconclusive", assessmentStatus: "limited", reviewRequired: true, finalScore: 75 });
    expect(result.decisionReasons.join(" ")).toContain("Audio-origin classification has not been validated sufficiently");
    expect(result.decisionReasons.join(" ")).not.toContain("visual assessment reports");
  });

  it("abstains on audio-origin uncertainty rather than treating a low diagnostic number as a negative", () => {
    const result = score(video({ aiLikelihood: 25, audioAssessment: "synthetic",
      suspiciousMoments: [{ timestamp: "00:00.0", category: "audio", severity: "medium",
        observation: "The narration has characteristic neural cadence and flat acoustic resonance." }],
    }));
    expect(result).toMatchObject({ verdict: "Inconclusive", assessmentStatus: "limited", reviewRequired: true, confidence: "Not calibrated", finalScore: 25 });
    expect(result.adjustments[0].reason).toContain("low numerical value");
  });

  it("keeps face manipulation and mixed footage visible in the decision", () => {
    expect(score(generated({
      visualClassification: "mixed_or_ai_edited",
      visualAssessment: "edited",
      identityManipulation: "face_swap",
      suspiciousMoments: [{ timestamp: "00:06", category: "identity", severity: "high", observation: "The replacement face separates from the head at an occlusion." }],
    }))).toMatchObject({ verdict: "AI indicators detected", evidenceLabel: "Mixed or AI-edited" });
  });

  it("does not treat a classification or high scalar alone as detection evidence", () => {
    expect(score(generated({ suspiciousMoments: [] }))).toMatchObject({ verdict: "Inconclusive", reviewRequired: true });
  });

  it("requires an audio observation to support an audio-only positive finding", () => {
    expect(score(video({
      aiLikelihood: 80,
      audioAssessment: "synthetic",
      suspiciousMoments: [{ timestamp: "00:02", category: "lighting", severity: "high", observation: "A reflection is unusual." }],
    }))).toMatchObject({ verdict: "Inconclusive", reviewRequired: true });
  });

  it("does not substitute a low-severity artifact for substantial AI evidence", () => {
    expect(score(generated({
      suspiciousMoments: [{ timestamp: "00:05", category: "temporal", severity: "low", observation: "Compression may explain a brief blur." }],
    }))).toMatchObject({ verdict: "Inconclusive", reviewRequired: true });
  });

  it("honors an explicitly insufficient evidence assessment even when an anomaly is cited", () => {
    expect(score(generated({ evidenceSufficiency: "insufficient" }))).toMatchObject({ verdict: "Inconclusive", assessmentStatus: "limited" });
  });

  it.each(["99:99", "00:21", "n/a"])("rejects unusable or out-of-duration citation %s as support", (timestamp) => {
    const result = score(generated({
      suspiciousMoments: [{ timestamp, category: "temporal", severity: "high", observation: "An impossible transition occurs." }],
    }));
    expect(result).toMatchObject({ verdict: "Inconclusive", assessmentStatus: "limited" });
    expect(result.decisionReasons.join(" ")).toContain("invalid timestamp");
  });

  it("does not claim full assessment coverage from a grounded observation in a limited scan", () => {
    expect(score(generated({ inspection: inspection({ audioCoverage: "limited" }) }))).toMatchObject({
      verdict: "AI indicators detected", assessmentStatus: "limited", reviewRequired: true,
    });
  });

  it("abstains when a model claims visual generation without access to the visuals", () => {
    expect(score(generated({ inspection: inspection({ visualCoverage: "unavailable" }) }))).toMatchObject({
      verdict: "Inconclusive", assessmentStatus: "conflicting",
    });
  });

  it.each([
    { visualCoverage: "limited" },
    { temporalCoverage: "limited" },
    { audioCoverage: "unavailable" },
    { reviewAgreement: "not_available" },
  ] satisfies Partial<VideoInspection>[])("does not clear a clip with incomplete inspection: %j", (overrides) => {
    expect(score(video({ inspection: inspection(overrides) }))).toMatchObject({ verdict: "Inconclusive", assessmentStatus: "limited" });
  });

  it("abstains when the model omits evidence sufficiency", () => {
    expect(score(video({ evidenceSufficiency: undefined }))).toMatchObject({ verdict: "Inconclusive", reviewRequired: true });
  });

  it("does not clear footage when degradation limits the evidence", () => {
    const result = score(video({ evidenceSufficiency: "limited", qualityIssues: ["Compression obscures the subject's face."] }));
    expect(result).toMatchObject({ verdict: "Inconclusive", reviewRequired: true, assessmentStatus: "limited" });
    expect(result.decisionReasons).toContain("Compression obscures the subject's face.");
  });

  it("does not convert ordinary compression notes into an unreadable-media decision", () => {
    expect(score(video({ qualityIssues: ["Standard video compression.", "Pillarboxing."] }))).toMatchObject({
      verdict: "No clear AI indicators", confidence: "Not calibrated", assessmentStatus: "complete",
    });
  });

  it("does not clear a clip after invalid observations have been removed upstream", () => {
    expect(score(video({ suspiciousMoments: [], inspection: inspection({ invalidObservations: true }) }))).toMatchObject({
      verdict: "Inconclusive", assessmentStatus: "limited", reviewRequired: true,
    });
  });

  it("does not treat a truly silent clip as a failed audio inspection", () => {
    expect(score(video({ audioAssessment: "inconclusive", inspection: inspection({ audioCoverage: "no_audio" }) }))).toMatchObject({
      verdict: "No clear AI indicators", assessmentStatus: "complete",
    });
  });

  it("abstains when the model reports synthetic audio on a silent clip", () => {
    expect(score(video({
      aiLikelihood: 80,
      audioAssessment: "synthetic",
      inspection: inspection({ audioCoverage: "no_audio" }),
      suspiciousMoments: [{ timestamp: "00:02", category: "audio", severity: "high", observation: "The voice is synthesized." }],
    }))).toMatchObject({ verdict: "Inconclusive", assessmentStatus: "conflicting" });
  });

  it("abstains when the independent review disagrees", () => {
    expect(score(generated({ inspection: inspection({ reviewAgreement: "disagree" }) }))).toMatchObject({
      verdict: "Inconclusive", assessmentStatus: "conflicting", reviewRequired: true,
    });
  });

  it("accepts an adequately resolved review without pretending the original passes agreed", () => {
    expect(score(video({ inspection: inspection({ reviewAgreement: "resolved" }) }))).toMatchObject({
      verdict: "No clear AI indicators", assessmentStatus: "complete",
    });
  });

  it("preserves uncertainty instead of using 49 versus 50 as a truth threshold", () => {
    for (const aiLikelihood of [49, 50]) {
      expect(score(video({ aiLikelihood, visualClassification: "inconclusive", visualAssessment: "inconclusive" }))).toMatchObject({
        verdict: "Inconclusive", confidence: "Not calibrated",
      });
    }
  });
});

describe("audio-only deployment safeguard", () => {
  const audioObservation: VideoAnalysis["suspiciousMoments"][number] = {
    timestamp: "00:02.5", category: "audio", severity: "high",
    observation: "The narration has unusually even cadence and acoustic resonance across phrase boundaries.",
  };
  const audioFlag = (overrides: Partial<VideoAnalysis> = {}) => video({
    aiLikelihood: 85, audioAssessment: "synthetic", suspiciousMoments: [audioObservation], ...overrides,
  });

  it.each([
    ["generated narration", "synthetic", 25],
    ["human narration falsely flagged by the model", "synthetic", 95],
    ["a weaker synthetic-audio claim", "likely_synthetic", 75],
  ] as const)("abstains on %s even with agreeing complete inspections", (_case, audioAssessment, aiLikelihood) => {
    const analysis = audioFlag({ audioAssessment, aiLikelihood });
    const original = structuredClone(analysis);
    const result = score(analysis);
    expect(result).toMatchObject({
      verdict: "Inconclusive", evidenceLabel: "Inconclusive", confidence: "Not calibrated",
      assessmentStatus: "limited", reviewRequired: true, baseScore: aiLikelihood, finalScore: aiLikelihood,
    });
    expect(result.decisionReasons.join(" ")).toContain("similar features can occur in human recordings");
    expect(analysis).toEqual(original);
  });

  it("does not let unsupported visual or identity labels bypass an audio-only safeguard", () => {
    const result = score(audioFlag({
      visualClassification: "mixed_or_ai_edited", visualAssessment: "edited", identityManipulation: "face_swap",
      suspiciousMoments: [audioObservation, { timestamp: "00:04", category: "temporal", severity: "low", observation: "A blurred edge may be ordinary compression." }],
    }));
    expect(result).toMatchObject({ verdict: "Inconclusive", assessmentStatus: "limited", reviewRequired: true });
    expect(result.decisionReasons.join(" ")).toContain("rely only on audio observations");
  });

  it("does not let a lip-sync label supported only by audio observations bypass the guard", () => {
    expect(score(audioFlag({ identityManipulation: "lip_sync_manipulation" }))).toMatchObject({
      verdict: "Inconclusive", assessmentStatus: "limited", reviewRequired: true,
    });
  });

  it.each(["inconclusive", "likely_recorded"] as const)("abstains on audio-only lip-sync inference even when audio itself is classified %s", (audioAssessment) => {
    const result = score(audioFlag({ identityManipulation: "lip_sync_manipulation", audioAssessment }));
    expect(result).toMatchObject({ verdict: "Inconclusive", assessmentStatus: "limited", reviewRequired: true });
    expect(result.decisionReasons.join(" ")).toContain("rely only on audio observations");
  });

  it("does not mistake an overall mixed-media label for a positive visual assessment", () => {
    expect(score(audioFlag({
      visualClassification: "mixed_or_ai_edited", visualAssessment: "likely_authentic",
      suspiciousMoments: [audioObservation, { timestamp: "00:04", category: "lighting", severity: "medium", observation: "A studio lighting change occurs at the edit." }],
    }))).toMatchObject({ verdict: "Inconclusive", assessmentStatus: "limited", reviewRequired: true });
  });

  it("retains a supported visual detection when an unverified audio finding is also present", () => {
    const result = score(generated({
      audioAssessment: "synthetic", suspiciousMoments: [...generated().suspiciousMoments, audioObservation],
    }));
    expect(result).toMatchObject({ verdict: "AI indicators detected", assessmentStatus: "complete", finalScore: 85 });
    expect(result.decisionReasons.join(" ")).toContain("visual assessment reports generation");
    expect(result.decisionReasons.join(" ")).toContain("audio-origin classification is unverified");
  });

  it("retains a grounded identity detection supported beyond audio", () => {
    expect(score(audioFlag({ identityManipulation: "face_swap", suspiciousMoments: [audioObservation, {
      timestamp: "00:06", category: "identity", severity: "high", observation: "The replacement face separates from the head at an occlusion.",
    }] }))).toMatchObject({ verdict: "AI indicators detected", assessmentStatus: "complete" });
  });

  it("keeps a consistent recorded-audio negative observational rather than forcing all audio reports to abstain", () => {
    expect(score(video({ audioAssessment: "likely_recorded" }))).toMatchObject({
      verdict: "No clear AI indicators", confidence: "Not calibrated", assessmentStatus: "complete", reviewRequired: false,
    });
  });

  it("preserves trusted generative provenance ahead of audio-origin uncertainty", () => {
    expect(score(audioFlag(), { provenance: { status: "found", indicatesGenerativeAi: true, valid: true, trusted: true } })).toMatchObject({
      verdict: "Verified AI provenance", confidence: "Verified provenance", assessmentStatus: "complete", reviewRequired: false,
    });
    expect(score(audioFlag(), { provenance: { status: "found", indicatesGenerativeAi: true, valid: true, trusted: false } }).verdict).toBe("Inconclusive");
  });

  it.each([
    { disclosure: { disclosed: true, reasons: ["Creator states the narration uses AI."] } },
    { metadata: { containsSyntheticMedia: true, hasExplicitAiDisclosure: false } },
    { comments: comments({ creatorAdmissionFound: true }) },
  ] satisfies Omit<ScoreInputs, "video">[])("preserves an explicit disclosure ahead of audio-only abstention: %j", (source) => {
    expect(score(audioFlag(), source)).toMatchObject({ verdict: "AI use disclosed", assessmentStatus: "complete", reviewRequired: false });
  });
});

describe("origin declarations and social context", () => {
  it("reserves verified provenance for valid trusted generative declarations", () => {
    const result = score(video({ inspection: undefined }), {
      provenance: { status: "found", indicatesGenerativeAi: true, valid: true, trusted: true },
    });
    expect(result).toMatchObject({
      verdict: "Verified AI provenance", confidence: "Verified provenance", evidenceLabel: "Verified synthetic",
      assessmentStatus: "complete", reviewRequired: false, baseScore: 5, finalScore: 5,
    });
  });

  it.each([
    { status: "found", indicatesGenerativeAi: true, valid: true, trusted: false },
    { status: "found", indicatesGenerativeAi: true, valid: false, trusted: true },
    { status: "invalid", indicatesGenerativeAi: true, valid: true, trusted: true },
    { status: "not_found", indicatesGenerativeAi: false, valid: null, trusted: null },
  ] satisfies NonNullable<ScoreInputs["provenance"]>[])("does not promote an invalid or missing credential: %j", (provenance) => {
    const result = score(video({ inspection: undefined }), { provenance });
    expect(result).toMatchObject({ verdict: "Inconclusive", confidence: "Not calibrated", finalScore: 5 });
  });

  it("keeps creator disclosure distinct from verified provenance and numerical model evidence", () => {
    expect(score(video(), {
      metadata: { containsSyntheticMedia: false, hasExplicitAiDisclosure: true },
    })).toMatchObject({ verdict: "AI use disclosed", confidence: "Not calibrated", finalScore: 5 });
  });

  it("recognizes an explicit Instagram-style disclosure independently of a weak visual pass", () => {
    const result = score(video({ inspection: undefined }), { disclosure: { disclosed: true, reasons: ["The creator explicitly states that this reel was made with generative AI."] } });
    expect(result).toMatchObject({ verdict: "AI use disclosed", confidence: "Not calibrated", finalScore: 5 });
    expect(result.decisionReasons).toContain("The creator explicitly states that this reel was made with generative AI.");
    expect(result.adjustments.at(-1)?.source).toBe("creator_disclosure");
  });

  it("recognizes a creator admission only from a completed comment pass", () => {
    expect(score(video(), { comments: comments({ creatorAdmissionFound: true }) }).verdict).toBe("AI use disclosed");
    expect(score(video(), { comments: comments({ status: "failed", creatorAdmissionFound: true }) }).verdict).toBe("No clear AI indicators");
  });

  it.each([
    { commentsClaimingAi: 0, commentsClaimingReal: 1 },
    { commentsClaimingAi: 100, commentsClaimingReal: 0 },
    { commentsClaimingAi: 0, commentsClaimingReal: 100 },
    { commentsClaimingAi: 0, commentsClaimingReal: 0 },
  ])("does not let audience claims change the score or verdict: %j", (overrides) => {
    const inputVideo = generated();
    const baseline = score(inputVideo);
    const withComments = score(inputVideo, { comments: comments(overrides) });
    expect(withComments).toMatchObject({
      finalScore: baseline.finalScore,
      verdict: baseline.verdict,
      confidence: baseline.confidence,
      assessmentStatus: baseline.assessmentStatus,
    });
    expect(withComments.adjustments.every((adjustment) => adjustment.delta === 0)).toBe(true);
  });
});
