/** Offline evaluation only. Never imported by an HTTP route. Labels and IDs are not sent to a model. */
import { readFile } from "node:fs/promises";
import { GoogleGenAI } from "@google/genai";
import { env, requireGeminiApiKey } from "@/lib/config/env";
import { withGeminiUploadedFile } from "./gemini";
import { saveUploadedVideo } from "./media";
import { buildResult, inspectMedia } from "./pipeline";
import { geminiVideoResultSchema } from "./schemas";

interface EvaluationInput { path: string; mimeType?: string; id?: string; metadata?: unknown }

async function evaluationMedia(input: EvaluationInput) {
  return saveUploadedVideo(new File([new Uint8Array(await readFile(input.path))], "video-under-review.mp4", { type: input.mimeType ?? "video/mp4" }));
}

export async function analyzeEvaluationVideo(input: EvaluationInput) {
  const media = await evaluationMedia(input);
  try {
    const findings = await inspectMedia(media);
    const result = buildResult({
      source: { platform: "upload", platformVideoId: media.sha256, canonicalKey: `upload:${media.sha256}`, canonicalUrl: null, inputUrl: null },
      ...findings, youtube: null, mediaReceipt: media.receipt,
    });
    return { ...result, aiScore: result.finalScore,
      decision: result.verdict === "Inconclusive" ? "abstain" : result.verdict === "No clear AI indicators" ? "not_ai" : "ai",
    };
  } finally { await media.cleanup(); }
}

export async function analyzeBaselineEvaluationVideo(input: EvaluationInput) {
  const baseline = await readFile(new URL("../../../eval/baseline-gemini.ts.txt", import.meta.url), "utf8");
  const prompt = baseline.match(/const VIDEO_SYSTEM_INSTRUCTION = `([\s\S]*?)`;/)?.[1];
  if (!prompt) throw new Error("The preserved baseline prompt could not be loaded.");
  // Exact e0188f6 request schema: live detector descriptions must not change the baseline rubric.
  const schema = JSON.parse(await readFile(new URL("../../../eval/baseline-video-schema.json", import.meta.url), "utf8")) as Record<string, unknown>;
  const parser = geminiVideoResultSchema.omit({ evidence_sufficiency: true, quality_issues: true });
  const client = new GoogleGenAI({ apiKey: requireGeminiApiKey(), apiVersion: "v1beta", httpOptions: { timeout: env.geminiHttpTimeoutMs } });
  const media = await evaluationMedia(input);
  const started = Date.now();
  try {
    return await withGeminiUploadedFile(media.filePath, media.mimeType, async (file) => {
      const interaction = await client.interactions.create({
        model: env.geminiModel,
        input: [{ type: "video", uri: file.uri, mime_type: file.mimeType, processing: env.geminiVideoProcessing },
          { type: "text", text: "Analyze the supplied media using the trusted system rubric." }],
        system_instruction: prompt,
        generation_config: { max_output_tokens: 2_048 },
        response_format: { type: "text", mime_type: "application/json", schema }, store: false,
      });
      if (interaction.status !== "completed" || !interaction.output_text) throw new Error("Baseline model interaction did not complete.");
      const raw = parser.parse(JSON.parse(interaction.output_text.replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "")));
      // Exact MVP video-only score rules. No label-bearing captions or source metadata enter either comparison.
      const score = Math.max(1, Math.min(99, Math.round(raw.ai_likelihood)));
      return {
        decision: score >= 50 ? "ai" : "not_ai", aiScore: score, finalScore: score,
        verdict: score >= 50 ? "Probably AI" : "Probably Not AI",
        confidence: score >= 85 || score <= 15 ? "High" : score >= 65 || score <= 35 ? "Medium" : "Low",
        model: env.geminiModel, videoProcessing: env.geminiVideoProcessing, analyzerVersion: "e0188f6-video-only",
        raw, elapsedMs: Date.now() - started, usage: interaction.usage, mediaReceipt: media.receipt,
      };
    });
  } finally { await media.cleanup(); }
}
