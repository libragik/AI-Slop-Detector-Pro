import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  create: vi.fn(), fetch: vi.fn(), get: vi.fn(), delete: vi.fn(),
  env: { geminiHttpTimeoutMs: 1_000, geminiFileTimeoutMs: 800, geminiFilePollMs: 200,
    geminiRetryMax: 2, geminiReviewFps: 6, geminiSweepFps: 2, geminiModel: "unchanged-model",
    geminiReviewModel: "unchanged-review-model", geminiVideoProcessing: "agentic" },
}));
vi.mock("@google/genai", () => ({ GoogleGenAI: class {
  interactions = { create: mocks.create };
  files = { get: mocks.get, delete: mocks.delete };
} }));
vi.mock("node:fs", () => ({ openAsBlob: async () => new Blob(["synthetic"]) }));
vi.mock("@/lib/config/env", () => ({ requireGeminiApiKey: () => "synthetic-key", env: mocks.env }));

import { analyzeCommentsWithGemini, analyzeVideoWithGemini, runGeminiVideoPass, withGeminiUploadedFile } from "@/lib/analyzer/gemini";

const never = () => new Promise<never>(() => undefined);
const input = { uri: "test://immutable-bytes", durationSeconds: 5, width: 640, height: 360, hasAudio: false };
const request = { kind: "sweep" as const, mode: "static" as const, model: "unchanged-model", fps: 2,
  prompt: "Unchanged synthetic instruction.", windows: [] };
const completed = () => ({ status: "completed", output_text: JSON.stringify({
  ai_likelihood: 10, visual_classification: "likely_not_ai_generated", visual_assessment: "likely_authentic",
  audio_assessment: "inconclusive", identity_manipulation: "none_detected", content_type: "camera_footage",
  summary: "No clear indicators.", suspicious_moments: [], evidence_against_ai: [], alternative_explanations: [],
  limitations: [], evidence_sufficiency: "sufficient", quality_issues: [],
}) });

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
  mocks.env.geminiHttpTimeoutMs = 1_000;
  mocks.env.geminiRetryMax = 2;
  mocks.create.mockReset().mockImplementation(never);
  mocks.fetch.mockReset().mockImplementation(async (_url, options) => options.headers["X-Goog-Upload-Command"] === "start"
    ? new Response(null, { headers: { "x-goog-upload-url": "https://generativelanguage.googleapis.com/upload/session" } })
    : new Response(JSON.stringify({ file: { name: "files/synthetic" } }), { headers: { "x-goog-upload-status": "final" } }));
  vi.stubGlobal("fetch", mocks.fetch);
  mocks.get.mockReset().mockResolvedValue({ state: "ACTIVE", uri: "test://ready" });
  mocks.delete.mockReset().mockResolvedValue({});
  vi.spyOn(console, "warn").mockImplementation(() => undefined);
});
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("Gemini independent operation deadlines", () => {
  it("allowlists diagnostic fields even when a rejected SDK value supplies arbitrary names and codes", async () => {
    mocks.env.geminiRetryMax = 0;
    const failure = { name: "private-error-name", code: "private-error-code", status: "429private",
      statusCode: 9999, message: "private-message", body: "private-body", headers: { authorization: "private-key" } };
    mocks.create.mockRejectedValueOnce(failure);
    await expect(runGeminiVideoPass(input, request)).rejects.toBe(failure);
    expect(console.warn).toHaveBeenCalledWith("[ai-slop-detector] Gemini review failed", {
      event: "gemini_video_pass_failed", stage: "request", passKind: "sweep", mode: "static",
      elapsedMs: 0, timeoutMs: 1000, interactionStatus: null,
      errorName: "UnknownError", errorCode: null, httpStatus: null,
    });
    expect(JSON.stringify(vi.mocked(console.warn).mock.calls)).not.toContain("private-");
  });

  it("bounds a never-settling video request and aborts it using actual Interactions request options", async () => {
    let settled = false;
    const pending = runGeminiVideoPass(input, request);
    pending.then(() => { settled = true; }, () => { settled = true; });
    const rejection = expect(pending).rejects.toMatchObject({ code: "GEMINI_TIMEOUT", message: "Gemini video inspection timed out" });
    await vi.advanceTimersByTimeAsync(999);
    expect(settled).toBe(false);
    expect(mocks.create).toHaveBeenCalledOnce();
    const [body, options] = mocks.create.mock.calls[0];
    expect(body).toMatchObject({ model: "unchanged-model", generation_config: { max_output_tokens: 8192, thinking_level: "high", seed: 41 }, store: false });
    expect(body.input[0]).toMatchObject({ uri: input.uri, processing: { type: "static", fps: 2 }, resolution: "high" });
    expect(options).toMatchObject({ timeout: 1_000, maxRetries: 0 });
    expect(options.signal.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await rejection;
    expect(options.signal.aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(mocks.create).toHaveBeenCalledOnce();
  });

  it("bounds a never-settling comment request without fabricating comment findings", async () => {
    const pending = analyzeCommentsWithGemini([{ text: "Synthetic fixture", isCreator: false }]);
    const rejection = expect(pending).rejects.toMatchObject({ code: "GEMINI_TIMEOUT", message: "Gemini comment analysis timed out" });
    await vi.advanceTimersByTimeAsync(1_000);
    await rejection;
    expect(mocks.create.mock.calls[0][1].signal.aborted).toBe(true);
    expect(mocks.create).toHaveBeenCalledOnce();
  });

  it("returns only the surviving review when its peer ignores abort indefinitely", async () => {
    mocks.create.mockResolvedValueOnce(completed()).mockImplementationOnce(never);
    const pending = analyzeVideoWithGemini(input);
    await vi.advanceTimersByTimeAsync(1_000);
    const result = await pending;
    expect(result.inspection).toMatchObject({ reviewAgreement: "not_available" });
    expect(result.inspection?.passes.map(pass => pass.status)).toEqual(["complete", "failed"]);
    expect(result.inspection?.passes[1]).toMatchObject({ inputTokens: null, outputTokens: null, aiLikelihood: null });
    expect(mocks.create).toHaveBeenCalledTimes(2);
  });

  it("stops if both requested reviews never settle", async () => {
    const pending = analyzeVideoWithGemini(input);
    const rejection = expect(pending).rejects.toThrow("could not complete either review pass");
    await vi.advanceTimersByTimeAsync(1_000);
    await rejection;
    expect(mocks.create).toHaveBeenCalledTimes(2);
    expect(mocks.create.mock.calls.every(([, options]) => options.signal.aborted)).toBe(true);
  });

  it("bounds an upload even if a transport does not settle after abort", async () => {
    mocks.fetch.mockImplementation(never);
    const consume = vi.fn();
    const pending = withGeminiUploadedFile("/synthetic/clip.mp4", "video/mp4", consume);
    const rejection = expect(pending).rejects.toMatchObject({ code: "GEMINI_TIMEOUT", message: "Gemini file upload timed out" });
    await vi.advanceTimersByTimeAsync(1_000);
    await rejection;
    expect(mocks.fetch.mock.calls[0][1].signal.aborted).toBe(true);
    expect(mocks.get).not.toHaveBeenCalled();
    expect(mocks.delete).not.toHaveBeenCalled();
    expect(consume).not.toHaveBeenCalled();
  });

  it("bounds a single stuck file-status read by the total processing deadline and cleans up", async () => {
    mocks.get.mockImplementation(never);
    const consume = vi.fn();
    const pending = withGeminiUploadedFile("/synthetic/clip.mp4", "video/mp4", consume);
    const rejection = expect(pending).rejects.toMatchObject({ code: "GEMINI_TIMEOUT", message: "Gemini file processing timed out" });
    await vi.advanceTimersByTimeAsync(800);
    await rejection;
    expect(mocks.get.mock.calls[0][0].config.abortSignal.aborted).toBe(true);
    expect(mocks.delete).toHaveBeenCalledOnce();
    expect(consume).not.toHaveBeenCalled();
  });

  it("returns a completed report even when cleanup ignores cancellation indefinitely", async () => {
    mocks.delete.mockImplementation(never);
    const warning = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const pending = withGeminiUploadedFile("/synthetic/clip.mp4", "video/mp4", async () => "completed-report");
    await vi.advanceTimersByTimeAsync(1_000);
    await expect(pending).resolves.toBe("completed-report");
    expect(mocks.delete.mock.calls[0][0].config.abortSignal.aborted).toBe(true);
    expect(mocks.delete).toHaveBeenCalledOnce();
    expect(warning).toHaveBeenCalledWith("[ai-slop-detector] Gemini temporary-file cleanup did not complete within its bounded attempt.");
  });

  it("preserves an inference failure when the cleanup request also never settles", async () => {
    mocks.delete.mockImplementation(never);
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const pending = withGeminiUploadedFile("/synthetic/clip.mp4", "video/mp4", async () => { throw new Error("original failure"); });
    const rejection = expect(pending).rejects.toThrow("original failure");
    await vi.advanceTimersByTimeAsync(1_000);
    await rejection;
  });

  it("accepts caller cancellation, cleans up independently, and does not start later SDK calls", async () => {
    mocks.get.mockImplementation(never);
    const controller = new AbortController();
    const consume = vi.fn();
    const pending = withGeminiUploadedFile("/synthetic/clip.mp4", "video/mp4", consume, controller.signal);
    const rejection = expect(pending).rejects.toMatchObject({ code: "GEMINI_CANCELLED" });
    await vi.advanceTimersByTimeAsync(100);
    controller.abort(new Error("Untrusted external cancellation detail"));
    await rejection;
    expect(mocks.get.mock.calls[0][0].config.abortSignal.aborted).toBe(true);
    expect(mocks.delete.mock.calls[0][0].config.abortSignal.aborted).toBe(false);
    expect(consume).not.toHaveBeenCalled();
    const second = expect(runGeminiVideoPass(input, request, controller.signal)).rejects.toMatchObject({ code: "GEMINI_CANCELLED" });
    await second;
    expect(mocks.create).not.toHaveBeenCalled();
  });

  it("cancels retry backoff without initiating a second billed request", async () => {
    mocks.env.geminiHttpTimeoutMs = 6_000;
    mocks.create.mockRejectedValueOnce({ status: 503 }).mockImplementation(never);
    const controller = new AbortController();
    const pending = runGeminiVideoPass(input, request, controller.signal);
    const rejection = expect(pending).rejects.toMatchObject({ code: "GEMINI_CANCELLED" });
    await vi.advanceTimersByTimeAsync(100);
    controller.abort();
    await rejection;
    await vi.advanceTimersByTimeAsync(10_000);
    expect(mocks.create).toHaveBeenCalledOnce();
  });

  it("uses one deadline across an allowed fast retry instead of restarting the budget", async () => {
    mocks.env.geminiHttpTimeoutMs = 6_000;
    mocks.create.mockRejectedValueOnce({ status: 503 }).mockImplementation(never);
    const pending = runGeminiVideoPass(input, request);
    const rejection = expect(pending).rejects.toMatchObject({ code: "GEMINI_TIMEOUT" });
    await vi.advanceTimersByTimeAsync(500);
    expect(mocks.create).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(5_500);
    await rejection;
    expect(mocks.create.mock.calls[1][1].signal.aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("clears deadlines after success and safely ignores a late rejected SDK promise", async () => {
    mocks.create.mockResolvedValueOnce(completed());
    await runGeminiVideoPass(input, request);
    expect(vi.getTimerCount()).toBe(0);
    let rejectLate: (error: Error) => void;
    mocks.create.mockImplementationOnce(() => new Promise((_, reject) => { rejectLate = reject; }));
    const pending = runGeminiVideoPass(input, request);
    const rejection = expect(pending).rejects.toMatchObject({ code: "GEMINI_TIMEOUT" });
    await vi.advanceTimersByTimeAsync(1_000);
    await rejection;
    rejectLate!(new Error("late SDK error"));
    await vi.advanceTimersByTimeAsync(0);
    expect(vi.getTimerCount()).toBe(0);
  });
});
