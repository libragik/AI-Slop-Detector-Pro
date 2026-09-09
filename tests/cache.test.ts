import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AnalysisResult, InspectionPass, VideoAnalysis } from "@/lib/analyzer/types";

const mock = vi.hoisted(() => ({
  from: vi.fn(), response: { data: null, error: null } as { data: unknown; error: unknown },
  signals: [] as AbortSignal[], waitForAbort: false,
}));

vi.mock("@supabase/supabase-js", () => ({ createClient: () => ({ from: mock.from }) }));

beforeEach(() => {
  vi.stubEnv("SIGHTENGINE_API_USER", "");
  vi.stubEnv("SIGHTENGINE_API_SECRET", "");
  vi.stubEnv("CACHE_ENABLED", "true");
  vi.stubEnv("SUPABASE_URL", "https://cache.example.test");
  vi.stubEnv("SUPABASE_SECRET_KEY", "test-key");
  mock.response = { data: null, error: null };
  mock.signals = [];
  mock.waitForAbort = false;
  mock.from.mockReset();
  mock.from.mockImplementation(() => {
    let signal: AbortSignal;
    const query = {
      select: vi.fn(() => query), eq: vi.fn(() => query), gt: vi.fn(() => query),
      maybeSingle: vi.fn(() => query), upsert: vi.fn(() => query),
      abortSignal: vi.fn((next: AbortSignal) => { signal = next; mock.signals.push(next); return query; }),
      then: (resolve: (value: typeof mock.response) => unknown, reject: (error: unknown) => unknown) => {
        const response = mock.waitForAbort ? new Promise<typeof mock.response>((_, fail) => {
          if (signal?.aborted) fail(signal.reason);
          else signal?.addEventListener("abort", () => fail(signal.reason), { once: true });
        }) : Promise.resolve(mock.response);
        return response.then(resolve, reject);
      },
    };
    return query;
  });
});

afterEach(() => { vi.unstubAllEnvs(); vi.restoreAllMocks(); vi.resetModules(); });

async function report(): Promise<AnalysisResult> {
  const fingerprint = await import("@/lib/analyzer/fingerprint");
  const video: VideoAnalysis = {
    aiLikelihood: 15, visualClassification: "likely_not_ai_generated", visualAssessment: "likely_authentic",
    audioAssessment: "likely_recorded", identityManipulation: "none_detected", contentType: "camera_footage",
    summary: "No clear AI indicators observed.", suspiciousMoments: [], evidenceAgainstAi: [],
    alternativeExplanations: [], limitations: [], agenticProcessingObserved: false,
    evidenceSufficiency: "sufficient", qualityIssues: [],
  };
  const pass: InspectionPass = {
    kind: "sweep", mode: "static", model: "test-model", fps: 2, status: "complete", elapsedMs: 10,
    aiLikelihood: 15, classification: "likely_not_ai_generated", summary: video.summary, inputTokens: 10,
    outputTokens: 10, intervals: [{ startSeconds: 0, endSeconds: 10 }], rawAnalysis: { ...video },
    consistencyIssues: [], validForCorroboration: true,
  };
  video.inspection = {
    visualCoverage: "adequate", temporalCoverage: "adequate", audioCoverage: "adequate", issues: [],
    reviewAgreement: "agree", strategy: "sweep_and_review", coverageBasis: "requested_sampling_and_model_report",
    durationSeconds: 10, passes: [pass, { ...pass, kind: "review" }],
  };
  return {
    id: "test-report", source: { platform: "youtube", platformVideoId: "9hE5-98ZeCg", canonicalKey: "youtube:9hE5-98ZeCg",
      canonicalUrl: "https://www.youtube.com/watch?v=9hE5-98ZeCg", inputUrl: "https://youtu.be/9hE5-98ZeCg" },
    baseScore: 15, finalScore: 15, verdict: "No clear AI indicators", confidence: "Not calibrated",
    assessmentStatus: "complete", reviewRequired: false, evidenceLabel: "No reliable evidence of AI found",
    decisionReasons: ["No clear AI indicators were observed; this does not establish authenticity."], adjustments: [],
    videoAnalysis: video, provenance: { status: "unavailable", embedded: false, valid: null, trusted: null,
      indicatesGenerativeAi: false, digitalSourceTypes: [], signer: null, validationMessages: [], note: "No asset credentials available." },
    youtube: null, mediaReceipt: null, socialContext: null, analyzedAt: new Date().toISOString(),
    analyzerVersion: fingerprint.analyzerCacheVersion(), detectorFingerprint: fingerprint.detectorFingerprint(),
    model: "test-model", videoProcessing: "static", cacheHit: false, limitations: [],
  };
}

describe("cached report boundary", () => {
  it.each(["missing", "failed", "different bytes"])("does not cache specialist evidence that is %s", async (defect) => {
    vi.stubEnv("SIGHTENGINE_API_USER", "test-user");
    vi.stubEnv("SIGHTENGINE_API_SECRET", "test-secret");
    vi.stubEnv("SIGHTENGINE_ENABLED", "true");
    const value = await report();
    value.mediaReceipt = { sha256: "a".repeat(64), durationSeconds: 1, width: 720, height: 1280,
      fps: 30, hasAudio: true, sizeBytes: 1000, mimeType: "video/mp4", mediaId: "9hE5-98ZeCg", postId: "9hE5-98ZeCg" };
    if (defect !== "missing") {
      const { aggregateSightengineEvidence } = await import("@/lib/analyzer/sightengine");
      value.specialistEvidence = aggregateSightengineEvidence([
        { positionSeconds: 0, aiGenerated: 0.001 }, { positionSeconds: 0.5, aiGenerated: 0.001 },
      ], { durationSeconds: 1, declaredIntervalSeconds: 0.5, technicalComplete: defect !== "failed" });
      value.specialistEvidence.sourceSha256 = defect === "different bytes" ? "b".repeat(64) : value.mediaReceipt.sha256;
    }
    mock.response.data = { result_json: value };
    const { findCachedAnalysis, saveCachedAnalysis } = await import("@/lib/analyzer/cache");
    await saveCachedAnalysis(value);
    expect(mock.from).not.toHaveBeenCalled();
    expect(await findCachedAnalysis(value.source.canonicalKey)).toBeNull();
  });
  it("returns a fully valid matching current report", async () => {
    const value = await report();
    mock.response.data = { result_json: value };
    const { findCachedAnalysis, saveCachedAnalysis } = await import("@/lib/analyzer/cache");
    expect(await findCachedAnalysis(value.source.canonicalKey)).toEqual({ ...value, cacheHit: true });
    await saveCachedAnalysis(value);
    expect(mock.from).toHaveBeenCalledTimes(2);
    expect(mock.signals).toHaveLength(2);
  });

  it.each(["source", "videoAnalysis", "provenance", "decisionReasons"])("rejects null %s instead of returning a broken UI cache hit", async (field) => {
    const value = await report();
    mock.response.data = { result_json: { ...value, [field]: null } };
    const { findCachedAnalysis } = await import("@/lib/analyzer/cache");
    expect(await findCachedAnalysis(value.source.canonicalKey)).toBeNull();
  });

  it.each(["canonical key", "fingerprint", "version", "inspection", "nested pass"])("rejects an incompatible or incomplete %s", async (defect) => {
    const value = await report();
    const requestedKey = value.source.canonicalKey;
    if (defect === "canonical key") value.source.canonicalKey = "youtube:another-clip";
    if (defect === "fingerprint") value.detectorFingerprint = "old-fingerprint";
    if (defect === "version") value.analyzerVersion = "old-version";
    if (defect === "inspection") delete value.videoAnalysis.inspection;
    if (defect === "nested pass") delete (value.videoAnalysis.inspection!.passes[0] as Partial<InspectionPass>).intervals;
    mock.response.data = { result_json: value };
    const { findCachedAnalysis } = await import("@/lib/analyzer/cache");
    expect(await findCachedAnalysis(requestedKey)).toBeNull();
  });

  it("requires a downloaded receipt and matching upload hash", async () => {
    const value = await report();
    const hash = "a".repeat(64);
    value.source = { platform: "upload", platformVideoId: hash, canonicalKey: `upload:${hash}`, canonicalUrl: null, inputUrl: null };
    const { findCachedAnalysis } = await import("@/lib/analyzer/cache");
    mock.response.data = { result_json: value };
    expect(await findCachedAnalysis(value.source.canonicalKey)).toBeNull();
    value.mediaReceipt = { sha256: "b".repeat(64), durationSeconds: 10, width: 720, height: 1280, fps: 30,
      hasAudio: true, sizeBytes: 1000, mimeType: "video/mp4", mediaId: null, postId: null };
    expect(await findCachedAnalysis(value.source.canonicalKey)).toBeNull();
    value.mediaReceipt.sha256 = hash;
    expect(await findCachedAnalysis(value.source.canonicalKey)).toMatchObject({ cacheHit: true });
  });

  it("neither saves nor reuses a partial provider-failure report", async () => {
    const value = await report();
    value.videoAnalysis.inspection!.passes[1].status = "failed";
    value.assessmentStatus = "limited";
    value.verdict = "Inconclusive";
    mock.response.data = { result_json: value };
    const { findCachedAnalysis, saveCachedAnalysis } = await import("@/lib/analyzer/cache");
    await saveCachedAnalysis(value);
    expect(mock.from).not.toHaveBeenCalled();
    expect(await findCachedAnalysis(value.source.canonicalKey)).toBeNull();
  });

  it("aborts stalled cache reads and treats the cache as a miss", async () => {
    const value = await report();
    mock.waitForAbort = true;
    const { findCachedAnalysis } = await import("@/lib/analyzer/cache");
    expect(await findCachedAnalysis(value.source.canonicalKey, 5)).toBeNull();
    expect(mock.signals[0].aborted).toBe(true);
  });

  it("aborts stalled cache writes without failing the completed analysis", async () => {
    const value = await report();
    mock.waitForAbort = true;
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const { saveCachedAnalysis } = await import("@/lib/analyzer/cache");
    await expect(saveCachedAnalysis(value, 5)).resolves.toBeUndefined();
    expect(mock.signals[0].aborted).toBe(true);
  });
});
