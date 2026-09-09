import { cacheConfigured, probeCacheOperational } from "@/lib/analyzer/cache";
import { analysisQueueStatus } from "@/lib/analyzer/guard";
import { providerStatus } from "@/lib/config/env";
import { analyzerCacheVersion, detectorFingerprint } from "@/lib/analyzer/fingerprint";
import { env } from "@/lib/config/env";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  const configuredProviders = providerStatus();
  const cacheConfiguredValue = cacheConfigured();
  const cacheOperational = cacheConfiguredValue ? await probeCacheOperational() : false;
  const providers = {
    ...configuredProviders,
    cache: cacheOperational,
    cacheConfigured: cacheConfiguredValue,
    analyzerVersion: analyzerCacheVersion(),
    detectorFingerprint: detectorFingerprint(),
    inspectionStrategy: "sweep_and_review",
    reviewModel: env.geminiReviewModel,
    calibrated: false,
  };
  return Response.json(
    {
      ok: providers.gemini,
      status: providers.gemini ? "ready" : "degraded",
      providers,
      limits: { maxMediaBytes: env.maxMediaBytes, maxDurationSeconds: env.maxDurationSeconds },
      queue: analysisQueueStatus(),
      timestamp: new Date().toISOString(),
    },
    { status: providers.gemini ? 200 : 503, headers: { "Cache-Control": "no-store" } },
  );
}
