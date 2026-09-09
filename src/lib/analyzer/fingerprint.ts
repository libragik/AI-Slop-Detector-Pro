import { createHash } from "node:crypto";
import { env } from "@/lib/config/env";
import * as policy from "./detection-policy";
import { geminiVideoJsonSchema } from "./schemas";

export function detectorFingerprint(): string {
  return createHash("sha256").update(JSON.stringify({
    policy, schema: geminiVideoJsonSchema, decisionPolicy: "consistent-evidence-2",
    mediaPolicy: "typed-provenance-single-media-2", analyzerVersion: env.analyzerVersion,
    executionPolicy: "abortable-files-large-upload-budgets-v5",
    model: env.geminiModel, reviewModel: env.geminiReviewModel, reviewMode: env.geminiVideoProcessing,
    sweepFps: env.geminiSweepFps, reviewFps: env.geminiReviewFps,
    resolution: "high", thinking: "high", seed: 41,
    c2pa: env.c2paEnabled, youtubeContext: Boolean(env.youtubeApiKey),
    youtubeCommentLimit: env.youtubeCommentLimit,
    specialist: {
      enabled: env.sightengineEnabled && Boolean(process.env.SIGHTENGINE_API_USER && process.env.SIGHTENGINE_API_SECRET),
      model: "genai", intervalSeconds: 0.5, policy: "sightengine-temporal-evidence-v1",
      decisionPolicy: "specialist-primary-positive-v3", transport: "sync-or-upload-and-async-v3",
      maxVideoSeconds: env.maxDurationSeconds, maxBytes: env.maxMediaBytes,
    },
  })).digest("hex");
}

export function analyzerCacheVersion(): string {
  return `${policy.DETECTOR_POLICY_VERSION}:${detectorFingerprint().slice(0, 24)}`;
}
