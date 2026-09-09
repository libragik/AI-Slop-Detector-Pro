import { z } from "zod";

export const suspiciousMomentSchema = z.object({
  timestamp: z.string().min(1).max(16),
  observation: z.string().min(1).max(600),
  severity: z.enum(["low", "medium", "high"]),
  category: z.enum([
    "anatomy",
    "text",
    "physics",
    "identity",
    "temporal",
    "lighting",
    "audio",
    "camera",
    "other",
  ]),
});

export const geminiVideoResultSchema = z.object({
  ai_likelihood: z.number().int().min(1).max(99),
  visual_classification: z.enum([
    "likely_ai_generated",
    "possibly_ai_generated",
    "mixed_or_ai_edited",
    "likely_not_ai_generated",
    "inconclusive",
  ]),
  visual_assessment: z.enum(["generated", "edited", "likely_authentic", "inconclusive"]),
  audio_assessment: z.enum(["synthetic", "likely_synthetic", "likely_recorded", "inconclusive"]),
  identity_manipulation: z.enum(["face_swap", "lip_sync_manipulation", "none_detected", "inconclusive"]),
  content_type: z.enum(["camera_footage", "animation", "cgi", "mixed", "unknown"]),
  summary: z.string().min(1).max(1_000),
  suspicious_moments: z.array(suspiciousMomentSchema).max(3),
  evidence_against_ai: z.array(z.string().min(1).max(500)).max(5),
  alternative_explanations: z.array(z.string().min(1).max(500)).max(5),
  limitations: z.array(z.string().min(1).max(500)).max(5),
  evidence_sufficiency: z.enum(["sufficient", "limited", "insufficient"]),
  quality_issues: z.array(z.string().min(1).max(500)).max(5),
});

export const geminiCommentResultSchema = z.object({
  ai_claim_comment_indices: z.array(z.number().int().min(1)).max(100),
  real_claim_comment_indices: z.array(z.number().int().min(1)).max(100),
  creator_admission_comment_indices: z.array(z.number().int().min(1)).max(100),
  credible_source_comment_indices: z.array(z.number().int().min(1)).max(100),
  comment_summary: z.string().min(1).max(800),
});

const stringArray = { type: "array", items: { type: "string" }, maxItems: 5 } as const;

export const geminiVideoJsonSchema = {
  type: "object",
  additionalProperties: false,
  properties: {
    ai_likelihood: {
      type: "integer",
      minimum: 1,
      maximum: 99,
      description: "An uncalibrated estimate based only on observable evidence in the supplied media.",
    },
    visual_classification: {
      type: "string",
      enum: [
        "likely_ai_generated",
        "possibly_ai_generated",
        "mixed_or_ai_edited",
        "likely_not_ai_generated",
        "inconclusive",
      ],
    },
    visual_assessment: { type: "string", enum: ["generated", "edited", "likely_authentic", "inconclusive"] },
    audio_assessment: { type: "string", enum: ["synthetic", "likely_synthetic", "likely_recorded", "inconclusive"] },
    identity_manipulation: { type: "string", enum: ["face_swap", "lip_sync_manipulation", "none_detected", "inconclusive"] },
    content_type: { type: "string", enum: ["camera_footage", "animation", "cgi", "mixed", "unknown"] },
    summary: { type: "string" },
    suspicious_moments: {
      type: "array",
      maxItems: 3,
      description: "Strongest timestamped evidence across visual, audio and identity findings. Any positive modality assessment requires matching supporting observations; a synthetic voiceover should have an audio observation even when no visual artifacts are found.",
      items: {
        type: "object",
        additionalProperties: false,
        properties: {
          timestamp: { type: "string", description: "Original-video timestamp as MM:SS.s (fractional seconds permitted)." },
          observation: { type: "string" },
          severity: { type: "string", enum: ["low", "medium", "high"] },
          category: { type: "string", enum: ["anatomy", "text", "physics", "identity", "temporal", "lighting", "audio", "camera", "other"] },
        },
        required: ["timestamp", "observation", "severity", "category"],
      },
    },
    evidence_against_ai: stringArray,
    alternative_explanations: stringArray,
    limitations: stringArray,
    evidence_sufficiency: {
      type: "string", enum: ["sufficient", "limited", "insufficient"],
      description: "Whether the supplied video is readable enough for this assessment. Sufficient means observable media, never proof of origin. Use limited/insufficient for missing, unreadable, extremely compressed or incomplete content.",
    },
    quality_issues: stringArray,
  },
  required: [
    "ai_likelihood",
    "visual_classification",
    "visual_assessment",
    "audio_assessment",
    "identity_manipulation",
    "content_type",
    "summary",
    "suspicious_moments",
    "evidence_against_ai",
    "alternative_explanations",
    "limitations",
    "evidence_sufficiency",
    "quality_issues",
  ],
} as const;

export const geminiCommentJsonSchema = {
  type: "object",
  additionalProperties: false,
  properties: {
    ai_claim_comment_indices: {
      type: "array",
      maxItems: 100,
      items: { type: "integer", minimum: 1 },
      description: "One-based indices of comments that clearly claim the media is AI-generated or materially AI-altered.",
    },
    real_claim_comment_indices: {
      type: "array",
      maxItems: 100,
      items: { type: "integer", minimum: 1 },
      description: "One-based indices of comments that clearly claim the media is real or authentic.",
    },
    creator_admission_comment_indices: {
      type: "array",
      maxItems: 100,
      items: { type: "integer", minimum: 1 },
      description: "One-based indices of comments marked isCreator=true that explicitly admit AI generation or material AI alteration.",
    },
    credible_source_comment_indices: {
      type: "array",
      maxItems: 100,
      items: { type: "integer", minimum: 1 },
      description: "One-based indices of comments containing specific firsthand or verifiable sourcing.",
    },
    comment_summary: { type: "string" },
  },
  required: [
    "ai_claim_comment_indices",
    "real_claim_comment_indices",
    "creator_admission_comment_indices",
    "credible_source_comment_indices",
    "comment_summary",
  ],
} as const;
