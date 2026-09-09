import { z } from "zod";

const finite = z.number().finite();
const sampleSchema = z.object({
  index: z.number().int().nonnegative(),
  rawPositionMilliseconds: finite.nullable(),
  positionSeconds: finite.nullable(),
  aiGenerated: finite.nullable(),
  valid: z.boolean(),
  positive: z.boolean().nullable(),
  issues: z.array(z.string()),
});

export const sightengineEvidenceSchema = z.object({
  schemaVersion: z.literal(1),
  provider: z.literal("sightengine"),
  model: z.literal("genai"),
  policyVersion: z.literal("sightengine-temporal-evidence-v1"),
  policyFingerprint: z.string().regex(/^[a-f0-9]{64}$/),
  status: z.enum(["complete", "limited", "unavailable"]),
  verdict: z.enum(["persistent_ai_indicators", "no_clear_indicators", "inconclusive"]),
  confidence: z.literal("Not calibrated"),
  reviewRequired: z.boolean(),
  sourceSha256: z.string().regex(/^[a-f0-9]{64}$/).nullable(),
  samples: z.array(sampleSchema),
  persistentRuns: z.array(z.object({
    sampleIndices: z.array(z.number().int().nonnegative()).min(2),
    sampledPositionsSeconds: z.array(finite).min(2),
    sampleScores: z.array(finite.min(0).max(1)).min(2),
    firstSampleSeconds: finite,
    lastSampleSeconds: finite,
    extentMeaning: z.literal("sample_endpoints_only_not_a_continuous_AI_interval"),
    adjacentSamplesAreIndependent: z.literal(false),
  })),
  isolatedAlerts: z.array(z.object({
    sampleIndex: z.number().int().nonnegative(),
    positionSeconds: finite,
    aiGenerated: finite.min(0).max(1),
    status: z.literal("unresolved"),
  })),
  coverage: z.object({
    complete: z.boolean(),
    durationSeconds: finite.positive().nullable(),
    declaredIntervalSeconds: finite.nullable(),
    issues: z.array(z.string()),
    sampledPositionsSeconds: z.array(finite),
    insufficientForSubsecondExclusion: z.literal(true),
    basis: z.literal("caller_declaration_and_returned_sample_positions_not_every_frame_inspection"),
  }),
  technicalIssues: z.array(z.string()),
  decisionReasons: z.array(z.string()),
  failureCode: z.enum([
    "not_configured", "server_only", "unsupported_input", "media_receipt_mismatch",
    "access_refused", "quota_or_rate_limit", "http_error", "network_error", "timeout",
    "response_too_large", "provider_rejected", "malformed_response", "accounting_mismatch",
    "incomplete_coverage",
  ]).nullable(),
  request: z.object({
    submissionAttempted: z.boolean(),
    operations: z.number().int().nonnegative().nullable(),
    httpStatus: z.number().int().min(100).max(599).nullable(),
    elapsedMs: finite.nonnegative(),
    transport: z.enum(["sync", "async"]).optional(),
    upload: z.enum(["direct", "upload_api"]).optional(),
    mediaId: z.string().nullable().optional(),
    uploadMediaId: z.string().nullable().optional(),
    jobStatus: z.string().nullable().optional(),
    pollCount: z.number().int().nonnegative().optional(),
    stopRequested: z.boolean().optional(),
    stopConfirmed: z.boolean().nullable().optional(),
    stage: z.enum(["validation", "create_upload", "upload", "submit", "poll", "complete"]).optional(),
  }),
  notProofOfOrigin: z.literal(true),
  scoresAreCalibratedProbabilities: z.literal(false),
  adjacentSamplesAreIndependent: z.literal(false),
});

export type SightengineEvidence = z.infer<typeof sightengineEvidenceSchema>;
export type SightengineSample = SightengineEvidence["samples"][number];
export type SightengineFailureCode = NonNullable<SightengineEvidence["failureCode"]>;
