import { z } from "zod";
import { sightengineEvidenceSchema } from "./sightengine-types";

// Shared report contract for the HTTP client and persisted result boundary.
// This module must not import React, runtime configuration, or server code.
const publicWebUrl = z.string().url().refine((value) => /^https?:\/\//i.test(value));

const suspiciousMomentSchema = z.object({
  timestamp: z.string().min(1),
  observation: z.string().min(1),
  severity: z.enum(["low", "medium", "high"]),
  category: z.enum(["anatomy", "text", "physics", "identity", "temporal", "lighting", "audio", "camera", "other"]),
});

const commentSchema = z.object({
  status: z.enum(["complete", "unavailable", "comments_disabled", "failed"]),
  sampleSize: z.number().int().nonnegative(),
  commentsClaimingAi: z.number().int().nonnegative(),
  commentsClaimingReal: z.number().int().nonnegative(),
  creatorAdmissionFound: z.boolean(),
  credibleSourceClaimFound: z.boolean(),
  commentSummary: z.string(),
  reason: z.string().optional(),
});

const videoFindingsSchema = z.object({
  aiLikelihood: z.number().min(1).max(99),
  visualClassification: z.enum(["likely_ai_generated", "possibly_ai_generated", "mixed_or_ai_edited", "likely_not_ai_generated", "inconclusive"]),
  visualAssessment: z.enum(["generated", "edited", "likely_authentic", "inconclusive"]),
  audioAssessment: z.enum(["synthetic", "likely_synthetic", "likely_recorded", "inconclusive"]),
  identityManipulation: z.enum(["face_swap", "lip_sync_manipulation", "none_detected", "inconclusive"]),
  contentType: z.enum(["camera_footage", "animation", "cgi", "mixed", "unknown"]),
  summary: z.string().min(1),
  suspiciousMoments: z.array(suspiciousMomentSchema),
  evidenceAgainstAi: z.array(z.string()),
  alternativeExplanations: z.array(z.string()),
  limitations: z.array(z.string()),
  agenticProcessingObserved: z.boolean(),
  evidenceSufficiency: z.enum(["sufficient", "limited", "insufficient"]).optional(),
  qualityIssues: z.array(z.string()).optional(),
});

export const apiResponseSchema = z.object({
  ok: z.literal(true),
  analysis: z.object({
    specialistEvidence: sightengineEvidenceSchema.nullable().optional(),
    id: z.string().min(1),
    source: z.object({
      platform: z.enum(["youtube", "tiktok", "instagram", "x", "upload"]),
      platformVideoId: z.string().min(1),
      canonicalKey: z.string().min(1),
      canonicalUrl: publicWebUrl.nullable(),
      inputUrl: publicWebUrl.nullable(),
    }),
    baseScore: z.number().min(1).max(99),
    finalScore: z.number().min(1).max(99),
    verdict: z.enum(["AI indicators detected", "No clear AI indicators", "Inconclusive", "AI use disclosed", "Verified AI provenance"]),
    confidence: z.enum(["Not calibrated", "Verified provenance"]),
    assessmentStatus: z.enum(["complete", "limited", "conflicting"]),
    reviewRequired: z.boolean(),
    decisionReasons: z.array(z.string().min(1)).min(1),
    evidenceLabel: z.string().min(1),
    adjustments: z.array(z.object({
      source: z.string(),
      rule: z.string(),
      scoreBefore: z.number(),
      scoreAfter: z.number(),
      delta: z.number(),
      reason: z.string(),
    })),
    videoAnalysis: z.object({
      ...videoFindingsSchema.shape,
      inspection: z.object({
        visualCoverage: z.enum(["adequate", "limited", "unavailable"]),
        temporalCoverage: z.enum(["adequate", "limited", "unknown"]),
        audioCoverage: z.enum(["adequate", "limited", "unavailable", "no_audio"]),
        issues: z.array(z.string()),
        reviewAgreement: z.enum(["agree", "resolved", "disagree", "not_available"]),
        invalidObservations: z.boolean().optional(),
        strategy: z.literal("sweep_and_review"),
        coverageBasis: z.literal("requested_sampling_and_model_report"),
        durationSeconds: z.number().nonnegative().nullable(),
        passes: z.array(z.object({
          kind: z.enum(["sweep", "review", "adjudication"]),
          mode: z.enum(["static", "agentic"]),
          model: z.string(),
          fps: z.number().positive().nullable(),
          status: z.enum(["complete", "failed"]),
          elapsedMs: z.number().nonnegative(),
          aiLikelihood: z.number().min(1).max(99).nullable(),
          classification: z.enum(["likely_ai_generated", "possibly_ai_generated", "mixed_or_ai_edited", "likely_not_ai_generated", "inconclusive"]).nullable(),
          summary: z.string(),
          inputTokens: z.number().nonnegative().nullable(),
          outputTokens: z.number().nonnegative().nullable(),
          intervals: z.array(z.object({ startSeconds: z.number().nonnegative(), endSeconds: z.number().nonnegative(), fps: z.number().positive().nullable().optional() })),
          rawAnalysis: videoFindingsSchema.optional(),
          consistencyIssues: z.array(z.string()).optional(),
          validForCorroboration: z.boolean().optional(),
        })),
      }).optional(),
    }),
    provenance: z.object({
      status: z.enum(["found", "not_found", "unavailable", "invalid", "error"]),
      embedded: z.boolean(),
      valid: z.boolean().nullable(),
      trusted: z.boolean().nullable(),
      indicatesGenerativeAi: z.boolean(),
      digitalSourceTypes: z.array(z.string()),
      signer: z.string().nullable(),
      validationMessages: z.array(z.string()),
      note: z.string(),
    }),
    youtube: z.object({
      status: z.enum(["complete", "unavailable", "failed"]),
      metadata: z.object({
        title: z.string().nullable(),
        description: z.string().nullable(),
        channelId: z.string().nullable(),
        channelTitle: z.string().nullable(),
        thumbnailUrl: publicWebUrl.nullable(),
        publishedAt: z.string().nullable(),
        duration: z.string().nullable(),
        containsSyntheticMedia: z.boolean(),
        hasExplicitAiDisclosure: z.boolean(),
        disclosureReasons: z.array(z.string()),
      }).nullable(),
      comments: commentSchema,
      reason: z.string().optional(),
    }).nullable(),
    mediaReceipt: z.object({
      sha256: z.string().regex(/^[a-f0-9]{64}$/),
      durationSeconds: z.number().positive(),
      width: z.number().positive(),
      height: z.number().positive(),
      fps: z.number().positive().nullable(),
      hasAudio: z.boolean(),
      sizeBytes: z.number().positive(),
      mimeType: z.string(),
      mediaId: z.string().nullable(),
      postId: z.string().nullable(),
    }).nullable(),
    socialContext: z.object({
      platform: z.enum(["instagram", "tiktok", "x"]),
      mediaId: z.string(),
      postId: z.string().nullable(),
      caption: z.string().nullable(),
      disclosureReasons: z.array(z.string()),
    }).nullable(),
    detectorFingerprint: z.string().min(1),
    analyzedAt: z.string().min(1),
    analyzerVersion: z.string().min(1),
    model: z.string().min(1),
    videoProcessing: z.enum(["agentic", "static"]),
    cacheHit: z.boolean(),
    limitations: z.array(z.string()),
  }),
});


export const analysisResultSchema = apiResponseSchema.shape.analysis;
