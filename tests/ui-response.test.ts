import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ResultReport } from "@/components/result-report";
import { aggregateSightengineEvidence } from "@/lib/analyzer/sightengine";

import { Detector, normalizeApiResult } from "@/components/detector";

const response = {
  ok: true,
  analysis: {
    id: "result-1",
    source: {
      platform: "youtube",
      platformVideoId: "9hE5-98ZeCg",
      canonicalKey: "youtube:9hE5-98ZeCg",
      canonicalUrl: "https://www.youtube.com/watch?v=9hE5-98ZeCg",
      inputUrl: "https://youtu.be/9hE5-98ZeCg",
    },
    baseScore: 15,
    finalScore: 15,
    verdict: "No clear AI indicators",
    confidence: "Not calibrated",
    assessmentStatus: "complete",
    reviewRequired: false,
    decisionReasons: ["Separate analysis passes found no clear AI indicators.", "This does not establish that the clip is authentic."],
    evidenceLabel: "No reliable evidence of AI found",
    adjustments: [
      {
        source: "gemini",
        rule: "base_score",
        scoreBefore: 15,
        scoreAfter: 15,
        delta: 0,
        reason: "Gemini visual-forensics likelihood is the starting score.",
      },
    ],
    videoAnalysis: {
      aiLikelihood: 15,
      visualClassification: "likely_not_ai_generated",
      visualAssessment: "likely_authentic",
      audioAssessment: "likely_recorded",
      identityManipulation: "none_detected",
      contentType: "camera_footage",
      summary: "No strong visual indicators of generative video were found.",
      suspiciousMoments: [],
      evidenceAgainstAi: ["Natural camera motion is consistent."],
      alternativeExplanations: [],
      limitations: ["Visual analysis is not proof."],
      agenticProcessingObserved: true,
      evidenceSufficiency: "sufficient",
      qualityIssues: [],
      inspection: {
        visualCoverage: "adequate", temporalCoverage: "adequate", audioCoverage: "adequate",
        issues: [], reviewAgreement: "agree", strategy: "sweep_and_review",
        coverageBasis: "requested_sampling_and_model_report", durationSeconds: 12,
        passes: [{ kind: "sweep", mode: "static", model: "test-model", fps: 2, status: "complete",
          elapsedMs: 10, aiLikelihood: 15, classification: "likely_not_ai_generated",
          summary: "No clear indicators", inputTokens: 12, outputTokens: 4,
          intervals: [{ startSeconds: 0, endSeconds: 12 }] }],
      },
    },
    provenance: {
      status: "unavailable",
      embedded: false,
      valid: null,
      trusted: null,
      indicatesGenerativeAi: false,
      digitalSourceTypes: [],
      signer: null,
      validationMessages: [],
      note: "C2PA inspection requires a media file.",
    },
    youtube: {
      status: "unavailable",
      metadata: null,
      comments: {
        status: "unavailable",
        sampleSize: 0,
        commentsClaimingAi: 0,
        commentsClaimingReal: 0,
        creatorAdmissionFound: false,
        credibleSourceClaimFound: false,
        commentSummary: "Comment evidence was not included in the score.",
        reason: "YOUTUBE_API_KEY is not configured",
      },
      reason: "YouTube metadata and comments are disabled.",
    },
    mediaReceipt: null,
    socialContext: null,
    detectorFingerprint: "test-detector-fingerprint",
    analyzedAt: "2026-09-02T18:40:00.000Z",
    analyzerVersion: "evidence-2-test",
    model: "gemini-3.7-flash",
    videoProcessing: "agentic",
    cacheHit: false,
    limitations: ["This is a probabilistic assessment, not proof."],
  },
} as const;

it("keeps a concise experimental limitation visible before a user starts a scan", () => {
  const html = renderToStaticMarkup(createElement(Detector));
  const notice = html.match(/<aside[^>]*aria-label="Important limitation"[^>]*>([\s\S]*?)<\/aside>/)?.[1];
  expect(notice).toContain("Experimental. Results can miss AI or flag real footage.");
  expect(notice).toContain("A scan cannot verify a video’s origin.");
});

describe("normalizeApiResult", () => {
  it("maps the server contract into a complete public report", () => {
    const result = normalizeApiResult(response);

    expect(result).toMatchObject({
      finalScore: 15,
      verdict: "No clear AI indicators",
      evidenceLabel: "No reliable evidence of AI found",
      platform: "youtube",
      sourceUrl: "https://www.youtube.com/watch?v=9hE5-98ZeCg",
      agenticProcessingUsed: true,
      analyzerVersion: "evidence-2-test",
    });
    expect(result.comments?.status).toBe("unavailable");
    expect(result.limitations).toHaveLength(1);
  });

  it("rejects a plausible-looking but incomplete response", () => {
    expect(() => normalizeApiResult({ ok: true, analysis: { finalScore: 50 } })).toThrow(
      "unexpected report format",
    );
  });

  it("accepts an X video report without YouTube context", () => {
    const xResponse = {
      ...response,
      analysis: {
        ...response.analysis,
        source: {
          platform: "x",
          platformVideoId: "1893456789012345678",
          canonicalKey: "x:1893456789012345678",
          canonicalUrl: "https://x.com/i/status/1893456789012345678",
          inputUrl: "https://x.com/i/status/1893456789012345678",
        },
        youtube: null,
      },
    } as const;

    expect(normalizeApiResult(xResponse)).toMatchObject({
      platform: "x",
      sourceUrl: "https://x.com/i/status/1893456789012345678",
      comments: { status: "unavailable" },
      metadata: { status: "unavailable" },
    });
  });
});

describe("evidence report presentation", () => {
  it("does not claim completed timeline sampling or separate reviews when every pass failed", () => {
    const result = normalizeApiResult({ ...response, analysis: {
      ...response.analysis, verdict: "Inconclusive", assessmentStatus: "limited", reviewRequired: true,
      videoAnalysis: { ...response.analysis.videoAnalysis, inspection: {
        ...response.analysis.videoAnalysis.inspection, temporalCoverage: "unknown", reviewAgreement: "not_available",
        passes: [{ ...response.analysis.videoAnalysis.inspection.passes[0], status: "failed" }],
      } },
    } });
    const html = renderToStaticMarkup(createElement(ResultReport, { result }));
    expect(html).toContain("0 completed analysis passes");
    expect(html).toContain("No completed inspection is available to establish coverage.");
    expect(html).toContain("Review incomplete");
    expect(html).not.toContain("sampled across the timeline and assessed in separate passes");
    expect(html).not.toContain("Separate reviews agree");
  });

  it("distinguishes a lone completed sweep from completed separate inspection passes", () => {
    const result = normalizeApiResult(response);
    const onePass = renderToStaticMarkup(createElement(ResultReport, { result }));
    expect(onePass).toContain("1 completed analysis pass");
    expect(onePass).toContain("The requested timeline sweep completed, but a separate review did not.");
    expect(onePass).not.toContain("Separate reviews agree");

    result.inspection!.passes.push({ ...result.inspection!.passes[0], kind: "review" });
    const twoPasses = renderToStaticMarkup(createElement(ResultReport, { result }));
    expect(twoPasses).toContain("The requested timeline sweep and a separate review completed.");
    expect(twoPasses).toContain("This does not verify that every frame was inspected.");
    expect(twoPasses).toContain("Separate reviews agree");
  });

  it("labels the report action as a rescan of the report's video", () => {
    const html = renderToStaticMarkup(createElement(ResultReport, { result: normalizeApiResult(response), onRescan: () => {} }));
    expect(html).toContain("Fresh scan of this report’s video");
    expect(html).not.toContain("Fresh scan of current input");
  });

  it("preserves and displays distinct full-timeline and detailed-window request rates", () => {
    const result = normalizeApiResult({ ...response, analysis: {
      ...response.analysis, videoAnalysis: { ...response.analysis.videoAnalysis, inspection: {
        ...response.analysis.videoAnalysis.inspection,
        passes: [{ ...response.analysis.videoAnalysis.inspection.passes[0], kind: "adjudication", intervals: [
          { startSeconds: 0, endSeconds: 12, fps: 2 }, { startSeconds: 2, endSeconds: 5, fps: 6 },
        ] }],
      } },
    } });
    expect(result.inspection?.passes[0].intervals[1].fps).toBe(6);
    const html = renderToStaticMarkup(createElement(ResultReport, { result }));
    expect(html).toContain("2 fps full timeline requested");
    expect(html).toContain("at 6 fps");
  });

  it("preserves fractional requested intervals instead of rounding away brief inspection windows", () => {
    const result = normalizeApiResult({ ...response, analysis: {
      ...response.analysis, videoAnalysis: { ...response.analysis.videoAnalysis, inspection: {
        ...response.analysis.videoAnalysis.inspection, durationSeconds: 71,
        passes: [{ ...response.analysis.videoAnalysis.inspection.passes[0], kind: "adjudication", intervals: [
          { startSeconds: 0, endSeconds: 71, fps: 2 },
          { startSeconds: 2.125, endSeconds: 2.875, fps: 6 },
          { startSeconds: 59.875, endSeconds: 60.125, fps: 6 },
        ] }],
      } },
    } });
    const html = renderToStaticMarkup(createElement(ResultReport, { result }));
    expect(html).toContain("0:00–1:11 at 2 fps");
    expect(html).toContain("0:02.125–0:02.875 at 6 fps");
    expect(html).toContain("0:59.875–1:00.125 at 6 fps");
  });

  it("describes trusted provenance as a verified AI assertion rather than certifying the entire source", () => {
    const result = normalizeApiResult({ ...response, analysis: {
      ...response.analysis, verdict: "Verified AI provenance", confidence: "Verified provenance",
      provenance: { ...response.analysis.provenance, status: "found", embedded: true, valid: true, trusted: true,
        indicatesGenerativeAi: true, digitalSourceTypes: ["trainedAlgorithmicMedia"], note: "The trusted credential declares generative media." },
    } });
    const html = renderToStaticMarkup(createElement(ResultReport, { result }));
    expect(html).toContain("AI credential verified");
    expect(html).toContain("VERIFIED AI ASSERTION");
    expect(html).not.toContain("Source verified");
    expect(html).not.toContain("VERIFIED AI SOURCE");

    result.provenance!.trusted = false;
    const untrustedHtml = renderToStaticMarkup(createElement(ResultReport, { result }));
    expect(untrustedHtml).toContain("UNVERIFIED AI ASSERTION");
    expect(untrustedHtml).not.toContain("AI credential verified");
  });

  it("preserves separate modality findings and inspection details", () => {
    const result = normalizeApiResult(response);
    expect(result).toMatchObject({
      visualAssessment: "likely_authentic",
      audioAssessment: "likely_recorded",
      identityManipulation: "none_detected",
      detectorFingerprint: "test-detector-fingerprint",
      inspection: { coverageBasis: "requested_sampling_and_model_report", reviewAgreement: "agree" },
    });
    expect(result.rawReport).toMatchObject({ id: "result-1", detectorFingerprint: "test-detector-fingerprint" });
  });

  it("shows inconclusive prominently even when the diagnostic model score is low", () => {
    const result = normalizeApiResult({ ...response, analysis: {
      ...response.analysis, verdict: "Inconclusive", assessmentStatus: "conflicting", reviewRequired: true,
      decisionReasons: ["The independent reviews disagree about AI generation."],
    } });
    const html = renderToStaticMarkup(createElement(ResultReport, { result }));
    expect(html).toContain("<h2>Inconclusive</h2>");
    expect(html).toContain("Conflicting evidence");
    expect(html).toContain("The independent reviews disagree");
    expect(html).not.toContain("score-dial");
    expect(html).not.toContain("High confidence");
    expect(html).not.toMatch(/\b\d+%/);
  });

  it("does not describe an absent audio track as inconclusive audio analysis", () => {
    const result = normalizeApiResult({ ...response, analysis: {
      ...response.analysis,
      videoAnalysis: { ...response.analysis.videoAnalysis, audioAssessment: "inconclusive", inspection: {
        ...response.analysis.videoAnalysis.inspection, audioCoverage: "no_audio",
      } },
    } });
    const html = renderToStaticMarkup(createElement(ResultReport, { result }));
    expect(html).toContain("No audio track");
  });

  it.each(["synthetic", "likely_synthetic"])("presents an audio-only %s flag as unverified alongside abstention", (audioAssessment) => {
    const result = normalizeApiResult({ ...response, analysis: {
      ...response.analysis, verdict: "Inconclusive", assessmentStatus: "limited", reviewRequired: true,
      decisionReasons: ["Audio-origin classification has not been validated sufficiently to determine AI use on its own."],
      videoAnalysis: { ...response.analysis.videoAnalysis, audioAssessment,
        suspiciousMoments: [{ timestamp: "00:02.5", category: "audio", severity: "high", observation: "The narration has unusually even cadence." }],
      },
    } });
    const html = renderToStaticMarkup(createElement(ResultReport, { result }));
    expect(html).toContain("<h2>Inconclusive</h2>");
    expect(html).toContain("Possible AI audio · unverified");
    expect(html).toContain("Audio-origin classification has not been validated sufficiently");
    expect(html).toContain("The narration has unusually even cadence.");
    expect(html).not.toContain("Synthesis indicators");
  });

  it("retains source identity and Instagram creator disclosures for the user", () => {
    const mediaReceipt = { sha256: "a".repeat(64), durationSeconds: 12, width: 720, height: 1280,
      fps: 30, hasAudio: true, sizeBytes: 2000000, mimeType: "video/mp4", mediaId: "Reel123", postId: "Reel123" };
    const result = normalizeApiResult({ ...response, analysis: {
      ...response.analysis,
      verdict: "AI use disclosed",
      evidenceLabel: "Disclosed synthetic or altered",
      decisionReasons: ["The creator explicitly discloses AI generation."],
      source: { ...response.analysis.source, platform: "instagram", canonicalUrl: "https://www.instagram.com/reel/Reel123/" },
      youtube: null,
      mediaReceipt,
      socialContext: { platform: "instagram", mediaId: "Reel123", postId: "Reel123", caption: "Made with AI.", disclosureReasons: ["The creator explicitly discloses AI generation."] },
    } });
    expect(result.mediaReceipt?.sha256).toBe(mediaReceipt.sha256);
    expect(result.metadata).toMatchObject({ status: "complete", disclosures: ["The creator explicitly discloses AI generation."] });
    const html = renderToStaticMarkup(createElement(ResultReport, { result }));
    expect(html).toContain("Made with AI.");
    expect(html).toContain("The creator explicitly discloses AI generation.");
    expect(html).toContain("720 × 1280");
    expect(html).toContain("Download report");
    expect(html).toContain("never submitted to a server");
  });

  it("accepts an incomplete review with unknown token usage without fabricating zeros", () => {
    const result = normalizeApiResult({ ...response, analysis: {
      ...response.analysis, verdict: "Inconclusive", assessmentStatus: "limited", reviewRequired: true,
      videoAnalysis: { ...response.analysis.videoAnalysis, inspection: {
        ...response.analysis.videoAnalysis.inspection, reviewAgreement: "not_available",
        passes: [{ ...response.analysis.videoAnalysis.inspection.passes[0], kind: "review", status: "failed", inputTokens: null, outputTokens: null }],
      } },
    } });
    expect(result.inspection?.passes[0]).toMatchObject({ status: "failed", inputTokens: null, outputTokens: null });
  });

  it("rejects a legacy confident binary verdict instead of relabeling it as new evidence", () => {
    expect(() => normalizeApiResult({ ...response, analysis: { ...response.analysis, verdict: "Probably Not AI", confidence: "High" } })).toThrow("unexpected report format");
  });

  it("preserves conflicting specialist evidence through API parsing and shows sampled positions separately from Gemini", () => {
    const specialistEvidence = aggregateSightengineEvidence([
      { positionSeconds: 0, aiGenerated: 0.99 }, { positionSeconds: 0.5, aiGenerated: 0.99 },
      { positionSeconds: 1, aiGenerated: 0.001 }, { positionSeconds: 1.5, aiGenerated: 0.8 },
    ], { durationSeconds: 2, declaredIntervalSeconds: 0.5, technicalComplete: true });
    const result = normalizeApiResult({ ...response, analysis: { ...response.analysis,
      verdict: "Inconclusive", assessmentStatus: "conflicting", reviewRequired: true,
      decisionReasons: ["Sightengine and Gemini disagree."], specialistEvidence,
    } });
    expect(result.specialistEvidence?.isolatedAlerts[0].positionSeconds).toBe(1.5);
    const html = renderToStaticMarkup(createElement(ResultReport, { result }));
    expect(html).toContain("<h2>Inconclusive</h2>");
    expect(html).toContain("Gemini visual review");
    expect(html).toContain("3 of 4 sampled frames flagged");
    expect(html).toContain("Unresolved isolated alerts");
    expect(html).toContain("0s to 0.5s");
    expect(html).not.toContain("99% confidence");
  });

  it("rejects an executable URL in a source receipt", () => {
    expect(() => normalizeApiResult({ ...response, analysis: { ...response.analysis,
      source: { ...response.analysis.source, canonicalUrl: "javascript:alert(1)" },
    } })).toThrow("unexpected report format");
  });
});
