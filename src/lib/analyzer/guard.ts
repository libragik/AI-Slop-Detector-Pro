import pLimit from "p-limit";

import { env } from "@/lib/config/env";

export class RateLimitError extends Error {
  readonly code = "RATE_LIMITED";
  readonly retryable = true;

  constructor(
    readonly retryAfterSeconds: number,
    message = "You have reached the fresh-scan limit. Try again later; cached lookups remain available.",
  ) {
    super(message);
    this.name = "RateLimitError";
  }
}

const requestLog = new Map<string, number[]>();
const limit = pLimit(env.analysisConcurrency);

export function hasAnalysisCapacity(
  active: number,
  pending: number,
  concurrency: number,
  maxQueue: number,
): boolean {
  return active < concurrency || pending < maxQueue;
}

export function assertFreshScanAllowed(clientKey: string): void {
  if (
    !hasAnalysisCapacity(
      limit.activeCount,
      limit.pendingCount,
      env.analysisConcurrency,
      env.analysisMaxQueue,
    )
  ) {
    throw new RateLimitError(
      15,
      "All analysis slots are busy. Try again shortly; cached lookups remain available.",
    );
  }
  const now = Date.now();
  const cutoff = now - env.rateLimitWindowMs;
  if (!requestLog.has(clientKey) && requestLog.size >= 10_000) {
    const oldestKey = requestLog.keys().next().value as string | undefined;
    if (oldestKey) requestLog.delete(oldestKey);
  }
  const recent = (requestLog.get(clientKey) ?? []).filter((time) => time > cutoff);
  if (recent.length >= env.rateLimitMaxFresh) {
    const retryAt = recent[0] + env.rateLimitWindowMs;
    throw new RateLimitError(Math.max(1, Math.ceil((retryAt - now) / 1_000)));
  }
  recent.push(now);
  requestLog.set(clientKey, recent);

  if (requestLog.size > 10_000) {
    for (const [key, times] of requestLog) {
      const active = times.filter((time) => time > cutoff);
      if (active.length) requestLog.set(key, active);
      else requestLog.delete(key);
    }
  }
}

export function runWithAnalysisConcurrency<T>(operation: () => Promise<T>): Promise<T> {
  return limit(operation);
}

export function analysisQueueStatus() {
  return {
    active: limit.activeCount,
    pending: limit.pendingCount,
    concurrency: env.analysisConcurrency,
    maxQueue: env.analysisMaxQueue,
  };
}
