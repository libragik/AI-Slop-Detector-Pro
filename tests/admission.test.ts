import { describe, expect, it } from "vitest";

import { RateLimitError, hasAnalysisCapacity } from "@/lib/analyzer/guard";
import { errorResponse } from "@/lib/analyzer/http";

describe("fresh analysis admission", () => {
  it("rejects immediately when every worker is occupied and queueing is disabled", () => {
    expect(hasAnalysisCapacity(2, 0, 2, 0)).toBe(false);
    expect(hasAnalysisCapacity(1, 0, 2, 0)).toBe(true);
  });

  it("allows only the explicitly configured number of queued requests", () => {
    expect(hasAnalysisCapacity(2, 0, 2, 1)).toBe(true);
    expect(hasAnalysisCapacity(2, 1, 2, 1)).toBe(false);
  });

  it("returns a stable retryable 429 for capacity pressure", async () => {
    const response = errorResponse(new RateLimitError(15, "All analysis slots are busy."));

    expect(response.status).toBe(429);
    expect(response.headers.get("Retry-After")).toBe("15");
    await expect(response.json()).resolves.toMatchObject({
      message: "All analysis slots are busy.",
      error: { code: "RATE_LIMITED", retryable: true, retryAfter: 15 },
    });
  });
});
