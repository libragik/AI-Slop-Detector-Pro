import { MAX_VIDEO_BYTES, MAX_VIDEO_SECONDS } from "@/lib/media-limits";

function integerEnv(name: string, fallback: number, minimum = 1): number {
  const raw = process.env[name];
  if (!raw) return fallback;

  const value = Number.parseInt(raw, 10);
  return Number.isFinite(value) && value >= minimum ? value : fallback;
}

function booleanEnv(name: string, fallback: boolean): boolean {
  const raw = process.env[name]?.trim().toLowerCase();
  if (!raw) return fallback;
  if (["1", "true", "yes", "on"].includes(raw)) return true;
  if (["0", "false", "no", "off"].includes(raw)) return false;
  return fallback;
}

/**
 * Server-only runtime configuration. Missing optional providers disable that
 * provider rather than making the application fail during `next build`.
 */
export const env = {
  geminiApiKey: process.env.GEMINI_API_KEY ?? process.env.GOOGLE_API_KEY,
  geminiModel: process.env.GEMINI_MODEL?.trim() || "gemini-3.5-flash-lite",
  geminiVideoProcessing:
    process.env.GEMINI_VIDEO_PROCESSING?.trim() === "agentic"
      ? ("agentic" as const)
      : ("static" as const),
  geminiFilePollMs: integerEnv("GEMINI_FILE_POLL_MS", 2_000, 250),
  geminiFileTimeoutMs: integerEnv("GEMINI_FILE_TIMEOUT_MS", 45_000, 5_000),
  geminiHttpTimeoutMs: integerEnv("GEMINI_HTTP_TIMEOUT_MS", 180_000, 5_000),
  geminiRetryMax: integerEnv("GEMINI_RETRY_MAX", 2, 0),
  geminiSweepFps: Math.min(integerEnv("GEMINI_SWEEP_FPS", 2), 8),
  geminiReviewModel: process.env.GEMINI_REVIEW_MODEL?.trim() || process.env.GEMINI_MODEL?.trim() || "gemini-3.5-flash-lite",
  geminiReviewFps: Math.min(integerEnv("GEMINI_REVIEW_FPS", 4), 12),

  youtubeApiKey: process.env.YOUTUBE_API_KEY,
  youtubeCommentLimit: Math.min(integerEnv("YOUTUBE_COMMENT_LIMIT", 100), 100),

  supabaseUrl: process.env.SUPABASE_URL,
  supabaseSecretKey:
    process.env.SUPABASE_SECRET_KEY ?? process.env.SUPABASE_SERVICE_ROLE_KEY,
  cacheEnabled: booleanEnv("CACHE_ENABLED", true),
  cacheTtlHours: integerEnv("CACHE_TTL_HOURS", 30 * 24),
  analyzerVersion: process.env.ANALYZER_VERSION?.trim() || "evidence-3",

  ytDlpPath: process.env.YT_DLP_PATH?.trim() || "yt-dlp",
  ffprobePath: process.env.FFPROBE_PATH?.trim() || "ffprobe",
  ytDlpTimeoutMs: integerEnv("YT_DLP_TIMEOUT_MS", 45_000, 5_000),
  maxMediaBytes: integerEnv("MAX_MEDIA_BYTES", MAX_VIDEO_BYTES),
  maxDurationSeconds: integerEnv("MAX_DURATION_SECONDS", MAX_VIDEO_SECONDS),
  c2paEnabled: booleanEnv("C2PA_ENABLED", true),
  sightengineEnabled: booleanEnv("SIGHTENGINE_ENABLED", true),

  analysisConcurrency: integerEnv("ANALYSIS_CONCURRENCY", 2),
  // Fresh scans are synchronous, so queueing is opt-in. The default rejects
  // once every worker is occupied instead of letting requests outlive the
  // hosting request window.
  analysisMaxQueue: integerEnv("ANALYSIS_MAX_QUEUE", 0, 0),
  rateLimitWindowMs: integerEnv("RATE_LIMIT_WINDOW_MS", 15 * 60 * 1_000),
  rateLimitMaxFresh: integerEnv("RATE_LIMIT_MAX_FRESH", 5),
} as const;

export function requireGeminiApiKey(): string {
  if (!env.geminiApiKey) {
    throw new Error("GEMINI_API_KEY is not configured");
  }
  return env.geminiApiKey;
}

export function providerStatus() {
  return {
    gemini: Boolean(env.geminiApiKey),
    youtube: Boolean(env.youtubeApiKey),
    cache:
      env.cacheEnabled && Boolean(env.supabaseUrl && env.supabaseSecretKey),
    c2pa: env.c2paEnabled,
    sightengine: env.sightengineEnabled && Boolean(process.env.SIGHTENGINE_API_USER && process.env.SIGHTENGINE_API_SECRET),
    model: env.geminiModel,
    videoProcessing: env.geminiVideoProcessing,
    analyzerVersion: env.analyzerVersion,
  };
}
