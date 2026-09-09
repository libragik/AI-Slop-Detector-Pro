import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Keep @google/genai real: mock only credentials and the network boundary.
vi.mock("@/lib/config/env", () => ({ requireGeminiApiKey: () => "offline-interactions-key", env: {
  geminiHttpTimeoutMs: 1_000, geminiRetryMax: 0, geminiReviewFps: 6,
} }));
import { runGeminiVideoPass } from "@/lib/analyzer/gemini";
import { reviewWindows } from "@/lib/analyzer/video-inspection";
import type { VideoAnalysis } from "@/lib/analyzer/types";

const input = { uri: "https://generativelanguage.googleapis.com/v1beta/files/offline-synthetic", durationSeconds: 5 };
const request = { kind: "sweep" as const, mode: "static" as const, model: "unchanged-test-model", fps: 2,
  prompt: "Private synthetic instruction", windows: [] };
const analysis = {
  ai_likelihood: 10, visual_classification: "likely_not_ai_generated", visual_assessment: "likely_authentic",
  audio_assessment: "inconclusive", identity_manipulation: "none_detected", content_type: "camera_footage",
  summary: "Synthetic completed analysis", suspicious_moments: [], evidence_against_ai: [], alternative_explanations: [],
  limitations: [], evidence_sufficiency: "sufficient", quality_issues: [],
};
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), {
  status, headers: { "content-type": "application/json" },
});
const complete = (text = JSON.stringify(analysis)) => json({
  id: "private-response-id", status: "completed", steps: [{ type: "model_output", content: [{ type: "text", text }] }],
});
let warning: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
  vi.stubGlobal("fetch", vi.fn(async () => complete()));
  warning = vi.spyOn(console, "warn").mockImplementation(() => undefined);
});
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("actual installed Interactions SDK transport", () => {
  it("serializes the observed 4.1-second review window as a valid protobuf Duration and records identical bounds", async () => {
    const windows = reviewWindows([{ suspiciousMoments: [{ timestamp: "00:04.1", severity: "medium" }] } as VideoAnalysis], 10);
    expect(windows[0].startSeconds).toBe(2.0999999999999996);
    const result = await runGeminiVideoPass({ ...input, durationSeconds: 10 }, { ...request, kind: "adjudication", windows });
    const outbound = vi.mocked(fetch).mock.calls[0][0] as Request;
    const body = await outbound.json();
    expect(body.input[0].processing).toEqual({ type: "static", fps: 2 });
    expect(body.input[1].processing).toEqual({ type: "static", fps: 6, start_offset: "2.1s", end_offset: "6.1s" });
    expect(result.receipt.intervals[1]).toEqual({ startSeconds: 2.1, endSeconds: 6.1, fps: 6 });
  });

  it("sends the existing inference payload to the correct endpoint with per-call options kept outside JSON", async () => {
    const result = await runGeminiVideoPass(input, request);
    expect(result.analysis.summary).toBe(analysis.summary);
    expect(fetch).toHaveBeenCalledOnce();
    const outbound = vi.mocked(fetch).mock.calls[0][0] as Request;
    expect(outbound).toBeInstanceOf(Request);
    expect(outbound.url).toBe("https://generativelanguage.googleapis.com/v1beta/interactions");
    expect(outbound.method).toBe("POST");
    expect(outbound.headers.get("x-goog-api-key")).toBe("offline-interactions-key");
    const body = await outbound.json();
    expect(body).toMatchObject({ model: request.model, store: false,
      generation_config: { max_output_tokens: 8192, thinking_level: "high", seed: 41 },
      input: [{ type: "video", uri: input.uri, processing: { type: "static", fps: 2 }, resolution: "high" },
        { type: "text", text: request.prompt }] });
    for (const key of ["timeout", "timeout_ms", "maxRetries", "signal", "retries"]) expect(body).not.toHaveProperty(key);
    expect(outbound.signal.aborted).toBe(false);
    expect(warning).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("propagates the hard deadline through real SDK Request.signal to a stalled fetch", async () => {
    // The real SDK also uses native AbortSignal.timeout, which Vitest's fake
    // clock does not advance. Keep both deadline mechanisms on the same clock.
    vi.useRealTimers();
    let outbound!: Request;
    let markFetchStarted!: () => void;
    const fetchStarted = new Promise<void>(resolve => { markFetchStarted = resolve; });
    vi.mocked(fetch).mockImplementation(input => new Promise<Response>((_resolve, reject) => {
      outbound = input as Request;
      outbound.signal.addEventListener("abort", () => reject(new DOMException("private detail", "AbortError")), { once: true });
      markFetchStarted();
    }));
    const pending = runGeminiVideoPass(input, request);
    const rejected = expect(pending).rejects.toMatchObject({ code: "GEMINI_TIMEOUT" });
    await fetchStarted;
    expect(outbound.signal.aborted).toBe(false);
    await rejected;
    await expect.poll(() => outbound.signal.aborted, { timeout: 500 }).toBe(true);
    expect(fetch).toHaveBeenCalledOnce();
    expect(warning).toHaveBeenCalledWith("[ai-slop-detector] Gemini review failed", {
      event: "gemini_video_pass_failed", stage: "request", passKind: "sweep", mode: "static",
      elapsedMs: expect.any(Number), timeoutMs: 1000, interactionStatus: null,
      errorName: "GeminiDeadlineError", errorCode: "GEMINI_TIMEOUT", httpStatus: null,
    });
    const diagnostics = warning.mock.calls.find(([message]) => message === "[ai-slop-detector] Gemini review failed")![1] as { elapsedMs: number };
    expect(diagnostics.elapsedMs).toBeGreaterThanOrEqual(900);
    expect(diagnostics.elapsedMs).toBeLessThan(5_000);
  });

  it("propagates parent cancellation through the real SDK without retrying", async () => {
    let outbound!: Request;
    vi.mocked(fetch).mockImplementation(input => new Promise<Response>((_resolve, reject) => {
      outbound = input as Request;
      outbound.signal.addEventListener("abort", () => reject(new DOMException("private detail", "AbortError")), { once: true });
    }));
    const controller = new AbortController();
    const pending = runGeminiVideoPass(input, request, controller.signal);
    const rejected = expect(pending).rejects.toMatchObject({ code: "GEMINI_CANCELLED" });
    await vi.advanceTimersByTimeAsync(1);
    controller.abort();
    await rejected;
    expect(outbound.signal.aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("preserves quota status while omitting arbitrary provider text and SDK headers from diagnostics", async () => {
    vi.mocked(fetch).mockResolvedValue(json({ error: { code: 429, status: "RESOURCE_EXHAUSTED",
      message: "private-secret https://private.example/path" } }, 429));
    await expect(runGeminiVideoPass(input, request)).rejects.toMatchObject({ status: 429 });
    expect(fetch).toHaveBeenCalledOnce();
    expect(warning).toHaveBeenCalledWith("[ai-slop-detector] Gemini review failed",
      expect.objectContaining({ stage: "request", errorName: "RateLimitError", httpStatus: 429, errorCode: null }));
    const serialized = JSON.stringify(warning.mock.calls);
    for (const forbidden of ["private-secret", "private.example", "offline-interactions-key", "headers", "body", input.uri, request.prompt]) {
      expect(serialized).not.toContain(forbidden);
    }
  });

  it("distinguishes provider completion failure from invalid structured output", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(json({ status: "budget_exceeded", errors: ["private-provider-detail"], steps: [] }));
    await expect(runGeminiVideoPass(input, request)).rejects.toThrow("did not complete");
    expect(warning.mock.calls[0][1]).toMatchObject({ stage: "completion", interactionStatus: "budget_exceeded", errorName: "Error" });
    vi.mocked(fetch).mockResolvedValueOnce(complete("private-invalid-JSON"));
    await expect(runGeminiVideoPass(input, request)).rejects.toBeInstanceOf(SyntaxError);
    expect(warning.mock.calls[1][1]).toMatchObject({ stage: "structured_output", interactionStatus: "completed", errorName: "SyntaxError" });
    expect(JSON.stringify(warning.mock.calls)).not.toContain("private-");
  });
});
