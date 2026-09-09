import { createHash } from "node:crypto";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ create: vi.fn(), cleanup: vi.fn(), saveUploadedVideo: vi.fn() }));
vi.mock("@google/genai", () => ({ GoogleGenAI: class { interactions = { create: mocks.create }; } }));
vi.mock("@/lib/config/env", () => ({
  requireGeminiApiKey: () => "test-only-key",
  env: { geminiModel: "baseline-test-model", geminiVideoProcessing: "agentic", geminiHttpTimeoutMs: 60_000 },
}));
vi.mock("@/lib/analyzer/gemini", () => ({
  analyzeVideoWithGemini: vi.fn(),
  withGeminiUploadedFile: async (_path: string, mimeType: string, consume: (file: { uri: string; mimeType: string }) => Promise<unknown>) => consume({ uri: "test://opaque", mimeType }),
}));
vi.mock("@/lib/analyzer/media", () => ({ saveUploadedVideo: mocks.saveUploadedVideo }));
vi.mock("@/lib/analyzer/c2pa", () => ({ inspectC2pa: vi.fn() }));
vi.mock("@/lib/analyzer/pipeline", () => ({ buildResult: vi.fn() }));

import { analyzeBaselineEvaluationVideo } from "@/lib/analyzer/evaluation";
import { geminiVideoJsonSchema } from "@/lib/analyzer/schemas";

const originalOutput = {
  ai_likelihood: 15, visual_classification: "likely_not_ai_generated", visual_assessment: "likely_authentic",
  audio_assessment: "likely_recorded", identity_manipulation: "none_detected", content_type: "camera_footage",
  summary: "No strong indicators were reported.", suspicious_moments: [], evidence_against_ai: [],
  alternative_explanations: [], limitations: ["Model judgment is not proof."],
};

let fixtureDirectory: string;
let fixturePath: string;
beforeAll(async () => {
  fixtureDirectory = await mkdtemp(join(tmpdir(), "detector-baseline-contract-"));
  fixturePath = join(fixtureDirectory, "opaque.mp4");
  // Media validation/upload and the provider are mocked; this test never sends media or invokes a model.
  await writeFile(fixturePath, "offline contract fixture");
});
afterAll(async () => { await rm(fixtureDirectory, { recursive: true, force: true }); });
beforeEach(() => {
  mocks.cleanup.mockReset().mockResolvedValue(undefined);
  mocks.saveUploadedVideo.mockReset().mockResolvedValue({
    filePath: "/temporary/opaque.mp4", mimeType: "video/mp4", sha256: "a".repeat(64),
    receipt: { sha256: "a".repeat(64), durationSeconds: 12 }, cleanup: mocks.cleanup,
  });
  mocks.create.mockReset().mockResolvedValue({ status: "completed", output_text: JSON.stringify(originalOutput) });
});

describe("preserved e0188f6 baseline contract", () => {
  it("retains the exact original JSON schema, including original required fields and descriptions", async () => {
    const schema = JSON.parse(await readFile(new URL("../eval/baseline-video-schema.json", import.meta.url), "utf8"));
    // Digest computed from the schema object extracted directly from e0188f6:src/lib/analyzer/schemas.ts.
    expect(createHash("sha256").update(JSON.stringify(schema)).digest("hex")).toBe("01918eeabf2135b1b98a492d98ce995ab334b2e785dd0f46e0717416efef20d5");
    expect(schema.required).toEqual([
      "ai_likelihood", "visual_classification", "visual_assessment", "audio_assessment", "identity_manipulation",
      "content_type", "summary", "suspicious_moments", "evidence_against_ai", "alternative_explanations", "limitations",
    ]);
    expect(schema.properties).not.toHaveProperty("evidence_sufficiency");
    expect(schema.properties).not.toHaveProperty("quality_issues");
    expect(schema.properties.suspicious_moments).not.toHaveProperty("description");
    expect(schema.properties.suspicious_moments.items.properties.timestamp.description).toBe("Timestamp as MM:SS or HH:MM:SS.");
  });

  it("sends the frozen schema even if the live detector schema changes", async () => {
    const frozenSchema = JSON.parse(await readFile(new URL("../eval/baseline-video-schema.json", import.meta.url), "utf8"));
    const liveMoments = geminiVideoJsonSchema.properties.suspicious_moments as { description: string };
    const previousDescription = liveMoments.description;
    try {
      liveMoments.description = "Live policy canary: this text must never enter the historical baseline.";
      const result = await analyzeBaselineEvaluationVideo({ path: fixturePath });
      const request = mocks.create.mock.calls[0][0];
      expect(request.response_format.schema).toEqual(frozenSchema);
      expect(JSON.stringify(request)).not.toContain("Live policy canary");
      expect(request.generation_config).toEqual({ max_output_tokens: 2_048 });
      expect(result).toMatchObject({ decision: "not_ai", finalScore: 15, confidence: "High", raw: originalOutput });
      expect(mocks.cleanup).toHaveBeenCalledOnce();
    } finally {
      liveMoments.description = previousDescription;
    }
  });

  it("keeps legacy fenced JSON parsing without requiring new quality fields", async () => {
    mocks.create.mockResolvedValue({ status: "completed", output_text: `\`\`\`json\n${JSON.stringify(originalOutput)}\n\`\`\`` });
    await expect(analyzeBaselineEvaluationVideo({ path: fixturePath })).resolves.toMatchObject({ raw: originalOutput, analyzerVersion: "e0188f6-video-only" });
  });

  it("still rejects an output missing an originally required field and cleans up", async () => {
    const incomplete: Partial<typeof originalOutput> = { ...originalOutput };
    delete incomplete.summary;
    mocks.create.mockResolvedValue({ status: "completed", output_text: JSON.stringify(incomplete) });
    await expect(analyzeBaselineEvaluationVideo({ path: fixturePath })).rejects.toThrow();
    expect(mocks.cleanup).toHaveBeenCalledOnce();
  });
});
