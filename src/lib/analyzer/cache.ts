import { createClient, type SupabaseClient } from "@supabase/supabase-js";

import { env } from "@/lib/config/env";
import type { AnalysisResult } from "./types";
import { analyzerCacheVersion, detectorFingerprint } from "./fingerprint";
import { analysisResultSchema } from "./result-schema";

let client: SupabaseClient | null | undefined;

function getClient(): SupabaseClient | null {
  if (client !== undefined) return client;
  if (!env.cacheEnabled || !env.supabaseUrl || !env.supabaseSecretKey) {
    client = null;
    return client;
  }

  client = createClient(env.supabaseUrl, env.supabaseSecretKey, {
    auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
    global: { headers: { "X-Client-Info": "ai-slop-detector-server" } },
  });
  return client;
}

function reusableResult(value: unknown, canonicalKey: string): value is AnalysisResult {
  const parsed = analysisResultSchema.safeParse(value);
  if (!parsed.success) return false;
  const result = parsed.data;
  if (result.detectorFingerprint !== detectorFingerprint() || result.analyzerVersion !== analyzerCacheVersion() ||
      result.source.canonicalKey !== canonicalKey) return false;

  // Every current detector run requests two inspections. A transient failed
  // pass must not become a reusable month-long result once the provider recovers.
  const inspection = result.videoAnalysis.inspection;
  if (!inspection || inspection.passes.length < 2 || inspection.passes.some((pass) => pass.status === "failed")) return false;
  if (env.sightengineEnabled && process.env.SIGHTENGINE_API_USER && process.env.SIGHTENGINE_API_SECRET) {
    const specialist = result.specialistEvidence;
    if (!specialist || specialist.status !== "complete" || !specialist.coverage.complete || specialist.failureCode ||
        !result.mediaReceipt || specialist.sourceSha256 !== result.mediaReceipt.sha256) return false;
  }
  if (result.source.platform !== "youtube" && !result.mediaReceipt) return false;
  if (result.source.platform === "upload" && (result.mediaReceipt?.sha256 !== result.source.platformVideoId ||
      canonicalKey !== `upload:${result.mediaReceipt?.sha256}` || result.source.canonicalUrl !== null || result.source.inputUrl !== null)) return false;
  if (result.source.platform !== "upload" && (!result.source.canonicalUrl || !result.source.inputUrl)) return false;
  return true;
}

export async function findCachedAnalysis(canonicalKey: string, timeoutMs = 2_000): Promise<AnalysisResult | null> {
  const supabase = getClient();
  if (!supabase) return null;

  try {
    const now = new Date().toISOString();
    const { data, error } = await supabase
      .from("video_analyses")
      .select("result_json")
      .eq("canonical_key", canonicalKey)
      .eq("status", "complete")
      .eq("analyzer_version", analyzerCacheVersion())
      .gt("expires_at", now)
      .abortSignal(AbortSignal.timeout(timeoutMs))
      .maybeSingle();
    if (error || !reusableResult(data?.result_json, canonicalKey)) return null;
    return { ...data.result_json, cacheHit: true };
  } catch {
    // Cache availability must never decide whether a scan can run.
    return null;
  }
}

export async function saveCachedAnalysis(result: AnalysisResult, timeoutMs = 2_000): Promise<void> {
  if (!reusableResult(result, result.source.canonicalKey)) return;
  const supabase = getClient();
  if (!supabase) return;

  const expiresAt = new Date(Date.now() + env.cacheTtlHours * 60 * 60 * 1_000).toISOString();
  try {
    const { error } = await supabase.from("video_analyses").upsert(
      {
        canonical_key: result.source.canonicalKey,
        canonical_url: result.source.canonicalUrl,
        platform: result.source.platform,
        platform_video_id: result.source.platformVideoId,
        status: "complete",
        analyzer_version: result.analyzerVersion,
        final_score: result.finalScore,
        evidence_label: result.evidenceLabel,
        result_json: result,
        expires_at: expiresAt,
        analyzed_at: result.analyzedAt,
        error_message: null,
      },
      { onConflict: "canonical_key" },
    ).abortSignal(AbortSignal.timeout(timeoutMs));
    if (error) {
      console.warn("[ai-slop-detector] Supabase cache write failed.");
    }
  } catch {
    console.warn("[ai-slop-detector] Supabase cache write failed.");
  }
}

export function cacheConfigured(): boolean {
  return getClient() !== null;
}

/**
 * A configured client does not prove the cache table or credentials work.
 * Keep the health probe small and bounded so an optional provider cannot hold
 * the application's readiness endpoint open.
 */
export async function probeCacheOperational(timeoutMs = 2_000): Promise<boolean> {
  const supabase = getClient();
  if (!supabase) return false;

  try {
    const { error } = await supabase
      .from("video_analyses")
      .select("id", { head: true })
      .limit(1)
      .abortSignal(AbortSignal.timeout(timeoutMs));
    return !error;
  } catch {
    return false;
  }
}
