import { beforeEach, describe, expect, it, vi } from "vitest";

const create = vi.hoisted(() => vi.fn());
vi.mock("@google/genai", () => ({ GoogleGenAI: class { interactions = { create }; } }));
vi.mock("@/lib/config/env", () => ({
  requireGeminiApiKey: () => "test-only-key",
  env: { geminiReviewFps: 6, geminiHttpTimeoutMs: 60_000, geminiRetryMax: 0 },
}));
import { runGeminiVideoPass } from "@/lib/analyzer/gemini";

beforeEach(() => {
  create.mockReset().mockResolvedValue({ status: "completed", output_text: JSON.stringify({
    ai_likelihood: 10, visual_classification: "likely_not_ai_generated", visual_assessment: "likely_authentic",
    audio_assessment: "inconclusive", identity_manipulation: "none_detected", content_type: "camera_footage",
    summary: "No clear indicators were observed.", suspicious_moments: [], evidence_against_ai: [],
    alternative_explanations: [], limitations: [], evidence_sufficiency: "sufficient", quality_issues: [],
  }) });
});

describe("requested sampling receipts", () => {
  it("retains the actual full-timeline and finer-window request rates separately", async () => {
    const result = await runGeminiVideoPass({ uri: "test://clip", durationSeconds: 10 }, {
      kind: "adjudication", model: "test-model", mode: "static", fps: 2, prompt: "Inspect the evidence.",
      windows: [{ startSeconds: 2, endSeconds: 5 }],
    });
    const input = create.mock.calls[0][0].input;
    expect(input[0].processing.fps).toBe(2);
    expect(input[1].processing).toEqual({ type: "static", fps: 6, start_offset: "2s", end_offset: "5s" });
    expect(result.receipt.intervals).toEqual([
      { startSeconds: 0, endSeconds: 10, fps: 2 }, { startSeconds: 2, endSeconds: 5, fps: 6 },
    ]);
  });

  it("does not claim a fixed sampling rate for an agentic review", async () => {
    const result = await runGeminiVideoPass({ uri: "test://clip", durationSeconds: 10 }, {
      kind: "review", model: "test-model", mode: "agentic", fps: 2, prompt: "Inspect the evidence.", windows: [],
    });
    expect(create.mock.calls[0][0].input[0].processing).toBe("agentic");
    expect(result.receipt.intervals).toEqual([{ startSeconds: 0, endSeconds: 10, fps: null }]);
  });

  it("uses at most 9fractional digits without dropping whole-second trailing zeros", async () => {
    const result = await runGeminiVideoPass({ uri: "test://clip", durationSeconds: 20 }, {
      kind: "adjudication", model: "test-model", mode: "static", fps: 2, prompt: "Inspect the evidence.",
      windows: [{ startSeconds: 0, endSeconds: 0.1234567896 }, { startSeconds: 10, endSeconds: 20 }],
    });
    const input = create.mock.calls[0][0].input;
    expect(input[1].processing).toMatchObject({ start_offset: "0s", end_offset: "0.12345679s" });
    expect(input[2].processing).toMatchObject({ start_offset: "10s", end_offset: "20s" });
    expect(result.receipt.intervals[1]).toEqual({ startSeconds: 0, endSeconds: 0.12345679, fps: 6 });
  });
});
