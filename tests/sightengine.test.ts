import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { aggregateSightengineEvidence, SIGHTENGINE_POLICY_FINGERPRINT } from "@/lib/analyzer/sightengine";
import { sightengineEvidenceSchema } from "@/lib/analyzer/sightengine-types";
import type { MediaReceipt } from "@/lib/analyzer/media-context";

const samples = (scores: unknown[], positions = scores.map((_, index) => index / 2)) =>
  scores.map((aiGenerated, index) => ({ positionSeconds: positions[index], aiGenerated }));
const evidence = (scores: unknown[], positions?: number[], durationSeconds = 4, technicalComplete = true) =>
  aggregateSightengineEvidence(samples(scores, positions), { durationSeconds, technicalComplete, declaredIntervalSeconds: 0.5 });
const bytes = new Uint8Array([0, 1, 2, 3, 4]);
const receipt = (overrides: Partial<MediaReceipt> = {}): MediaReceipt => ({
  sha256: createHash("sha256").update(bytes).digest("hex"), durationSeconds: 4,
  width: 640, height: 360, fps: 24, hasAudio: false, sizeBytes: bytes.length,
  mimeType: "video/mp4", mediaId: null, postId: null, ...overrides,
});
const payload = (scores: unknown[] = Array(8).fill(0), positions = scores.map((_, index) => index * 500)) => ({
  status: "success", request: { id: "local-synthetic-id", timestamp: 123, operations: scores.length * 5 },
  data: { frames: scores.map((ai_generated, index) => ({ info: { position: positions[index] }, type: { ai_generated } })) },
});
const jsonResponse = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });

describe("Sightengine fixed temporal evidence", () => {
  it("retains persistent runs, isolated unresolved alerts and correlated sample qualification", () => {
    const result = evidence([0, 0.5, 1, 0, 0.99, 0.99, 0, 0.9]);
    expect(result).toMatchObject({
      status: "complete", verdict: "persistent_ai_indicators", confidence: "Not calibrated", reviewRequired: true,
      adjacentSamplesAreIndependent: false, scoresAreCalibratedProbabilities: false,
      coverage: { complete: true, insufficientForSubsecondExclusion: true },
    });
    expect(result.persistentRuns.map((run) => run.sampleIndices)).toEqual([[1, 2], [4, 5]]);
    expect(result.persistentRuns[0]).toMatchObject({ sampledPositionsSeconds: [0.5, 1], sampleScores: [0.5, 1], lastSampleSeconds: 1 });
    expect(result.isolatedAlerts).toEqual([{ sampleIndex: 7, positionSeconds: 3.5, aiGenerated: 0.9, status: "unresolved" }]);
    expect(sightengineEvidenceSchema.parse(result)).toEqual(result);
  });

  it("does not turn a singleton or incomplete no-hit scan into a negative", () => {
    expect(evidence([0, 0, 0.99, 0, 0, 0, 0, 0]).verdict).toBe("inconclusive");
    expect(evidence(Array(8).fill(0), undefined, 4, false).verdict).toBe("inconclusive");
    const complete = evidence(Array(8).fill(0));
    expect(complete.verdict).toBe("no_clear_indicators");
    expect(complete.notProofOfOrigin).toBe(true);
    expect(complete.decisionReasons.join(" ")).toContain("including subsecond inserts");
  });

  it("requires the sampling interval to be declared and does not infer it from a few positions", () => {
    expect(aggregateSightengineEvidence(samples(Array(8).fill(0)), {
      durationSeconds: 4, technicalComplete: true, declaredIntervalSeconds: undefined,
    })).toMatchObject({ verdict: "inconclusive", status: "limited" });
  });

  it("preserves runs on incomplete input while refusing a complete verdict", () => {
    const result = evidence([1, 1, 0], [1, 1.5, 2]);
    expect(result.verdict).toBe("inconclusive");
    expect(result.persistentRuns[0].sampleIndices).toEqual([0, 1]);
    expect(result.coverage.issues).toEqual(["initial_coverage_gap", "terminal_coverage_gap"]);
  });

  it("does not join across a negative, malformed, duplicate or out-of-order observation", () => {
    for (const [scores, positions] of [
      [[1, 0, 1], [0, 0.2, 0.4]], [[1, null, 1], [0, 0.2, 0.4]],
      [[1, 1, 0], [0, 0, 0.5]], [[1, 1, 0], [0.5, 0, 0.8]],
    ] as [unknown[], number[]][]) {
      const result = evidence(scores, positions, 1);
      expect(result.persistentRuns).toEqual([]);
      expect(result.isolatedAlerts).toHaveLength(2);
      expect(result.verdict).toBe("inconclusive");
    }
  });

  it("matches the frozen Python policy on independent synthetic boundary and coverage cases", () => {
    const fixtures = [
      { scores: [0, 0.5, 1, 0, 0, 1, 0, 0], positions: [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5], duration: 4 },
      { scores: [0, 1, 1, 0], positions: [0, 0.6, 1.2, 1.8], duration: 2.4 },
      { scores: [1, 1, 0], positions: [0, 0.6000000001, 1], duration: 1.5 },
      { scores: [0, 0, 0], positions: [0.1, 0.6, 1.1], duration: 1.7 },
      { scores: [0, 0, 0], positions: [0.1000000001, 0.6, 1.1], duration: 1.7 },
      { scores: [0, 0, 0], positions: [0.1, 0.6, 1.1], duration: 1.7000000001 },
      { scores: [1, null, 1], positions: [0, 0.2, 0.4], duration: 0.8 },
      { scores: [1, 1, 0], positions: [0, 0, 0.5], duration: 1 },
      { scores: [1, 1, 0], positions: [0.5, 0, 0.8], duration: 1 },
      { scores: [], positions: [], duration: 4 },
    ];
    const python = existsSync(join(process.cwd(), "eval/.venv/bin/python")) ? join(process.cwd(), "eval/.venv/bin/python") : "python3";
    const program = [
      "import importlib.util,json,sys",
      "s=importlib.util.spec_from_file_location('policy','scripts/sightengine-temporal-evidence.py')",
      "m=importlib.util.module_from_spec(s);s.loader.exec_module(m)",
      "f=json.load(sys.stdin)",
      "print(json.dumps([m.aggregate_evidence([{'positionSeconds':p,'aiGenerated':v} for p,v in zip(x['positions'],x['scores'])],duration_seconds=x['duration'],technical_complete=True,declared_interval_seconds=.5) for x in f]))",
    ].join("\n");
    const expected = JSON.parse(execFileSync(python, ["-c", program], { input: JSON.stringify(fixtures), encoding: "utf8", timeout: 10_000 }));
    fixtures.forEach((fixture, index) => {
      const actual = evidence(fixture.scores, fixture.positions, fixture.duration);
      expect(actual.policyFingerprint).toBe(expected[index].policyFingerprint);
      for (const field of ["verdict", "reviewRequired", "persistentRuns", "isolatedAlerts", "coverage", "technicalIssues", "decisionReasons"] as const) {
        expect(actual[field], `fixture ${index}: ${field}`).toEqual(expected[index][field]);
      }
    });
    expect(expected[0].policyFingerprint).toBe(SIGHTENGINE_POLICY_FINGERPRINT);
  });

  it.each([NaN, Infinity, -Infinity, -0.1, 1.1, true, "0.9"])("abstains on invalid score %s with JSON-safe evidence", (score) => {
    const result = evidence([score, 0, 0, 0, 0, 0, 0, 0]);
    expect(result.verdict).toBe("inconclusive");
    expect(sightengineEvidenceSchema.safeParse(result).success).toBe(true);
  });
});

describe("Sightengine bounded server client (mock transport only)", () => {
  let analyzeSightengineVideo: typeof import("@/lib/analyzer/sightengine")["analyzeSightengineVideo"];
  let isSightengineConfigured: typeof import("@/lib/analyzer/sightengine")["isSightengineConfigured"];
  beforeEach(async () => {
    vi.resetModules();
    ({ analyzeSightengineVideo, isSightengineConfigured } = await import("@/lib/analyzer/sightengine"));
    vi.stubEnv("SIGHTENGINE_API_USER", "synthetic-user-secret");
    vi.stubEnv("SIGHTENGINE_API_SECRET", "synthetic-api-secret");
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("Unexpected mock request"))));
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("does not submit when credentials are absent or code is invoked in a browser", async () => {
    vi.stubEnv("SIGHTENGINE_API_SECRET", "");
    expect(isSightengineConfigured()).toBe(false);
    expect(await analyzeSightengineVideo({ bytes, receipt: receipt() })).toMatchObject({
      verdict: "inconclusive", status: "unavailable", failureCode: "not_configured", request: { submissionAttempted: false },
    });
    vi.stubEnv("SIGHTENGINE_API_SECRET", "synthetic-api-secret");
    vi.stubGlobal("window", {});
    expect(isSightengineConfigured()).toBe(false);
    expect((await analyzeSightengineVideo({ bytes, receipt: receipt() })).failureCode).toBe("server_only");
    expect(fetch).not.toHaveBeenCalled();
  });

  it.each([0, 180.1, NaN])("rejects unsupported duration %s before submission", async (durationSeconds) => {
    expect((await analyzeSightengineVideo({ bytes, receipt: receipt({ durationSeconds }) })).failureCode).toBe("unsupported_input");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("rejects media larger than 500 MB and mismatched byte hashes or sizes", async () => {
    expect((await analyzeSightengineVideo({ bytes: new Uint8Array(500_000_001), receipt: receipt() })).failureCode).toBe("unsupported_input");
    expect((await analyzeSightengineVideo({ bytes, receipt: receipt({ sha256: "0".repeat(64) }) })).failureCode).toBe("media_receipt_mismatch");
    expect((await analyzeSightengineVideo({ bytes, receipt: receipt({ sizeBytes: 2 }) })).failureCode).toBe("media_receipt_mismatch");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("posts exact copied bytes with neutral multipart fields and normalizes milliseconds", async () => {
    const mutable = bytes.slice();
    vi.mocked(fetch).mockImplementation(async (url, init) => {
      expect(url).toBe("https://api.sightengine.com/1.0/video/check-sync.json");
      expect(init).toMatchObject({ method: "POST", redirect: "error" });
      expect(init?.signal).toBeInstanceOf(AbortSignal);
      const form = init?.body as FormData;
      expect(Array.from(form.keys())).toEqual(["media", "models", "interval", "api_user", "api_secret"]);
      expect(form.get("models")).toBe("genai");
      expect(form.get("interval")).toBe("0.5");
      mutable.fill(9);
      const file = form.get("media") as File;
      expect(file.name).toBe("clip.mp4");
      expect(new Uint8Array(await file.arrayBuffer())).toEqual(bytes);
      return jsonResponse(payload([0, 0.99, 0.99, 0, 0, 0.99, 0, 0]));
    });
    const result = await analyzeSightengineVideo({ bytes: mutable, receipt: receipt() });
    expect(result).toMatchObject({ status: "complete", verdict: "persistent_ai_indicators", reviewRequired: true, sourceSha256: receipt().sha256 });
    expect(result.samples[1]).toMatchObject({ rawPositionMilliseconds: 500, positionSeconds: 0.5 });
    expect(result.request).toMatchObject({ submissionAttempted: true, operations: 40, httpStatus: 200 });
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(sightengineEvidenceSchema.safeParse(result).success).toBe(true);
    expect(JSON.stringify(result)).not.toContain("synthetic-api-secret");
    expect(JSON.stringify(result)).not.toContain("synthetic-user-secret");
  });

  it.each([[401, "access_refused"], [403, "access_refused"], [402, "quota_or_rate_limit"], [429, "quota_or_rate_limit"], [302, "http_error"], [500, "http_error"]])(
    "fails closed on HTTP %s without retries or provider error text", async (status, failureCode) => {
      vi.mocked(fetch).mockResolvedValue(new Response("synthetic-api-secret", { status: Number(status), headers: { location: "https://untrusted.example" } }));
      const result = await analyzeSightengineVideo({ bytes, receipt: receipt() });
      expect(result).toMatchObject({ verdict: "inconclusive", status: "unavailable", failureCode, request: { submissionAttempted: true } });
      expect(JSON.stringify(result)).not.toContain("synthetic-api-secret");
      expect(fetch).toHaveBeenCalledTimes(1);
    },
  );

  it("sanitizes network and status-failure payloads without returning exception text", async () => {
    vi.mocked(fetch).mockRejectedValue(new Error("synthetic-api-secret synthetic-user-secret"));
    let result = await analyzeSightengineVideo({ bytes, receipt: receipt() });
    expect(result.failureCode).toBe("network_error");
    expect(JSON.stringify(result)).not.toContain("synthetic-");
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ status: "failure", error: { message: "synthetic-api-secret" } }));
    result = await analyzeSightengineVideo({ bytes, receipt: receipt() });
    expect(result.failureCode).toBe("provider_rejected");
    expect(JSON.stringify(result)).not.toContain("synthetic-");
  });

  it("reports a failed response stream as a network failure and discards partial JSON", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(new ReadableStream({
      start(controller) { controller.error(new TypeError("synthetic-api-secret connection reset")); },
    })));
    const result = await analyzeSightengineVideo({ bytes, receipt: receipt() });
    expect(result).toMatchObject({ failureCode: "network_error", verdict: "inconclusive", status: "unavailable" });
    expect(JSON.stringify(result)).not.toContain("synthetic-api-secret");
  });

  it.each([0, 1, 35, 41, null])("retains observed samples but abstains on inconsistent accounting %s", async (operations) => {
    const body: Record<string, unknown> = payload(Array(8).fill(0.99));
    (body.request as Record<string, unknown>).operations = operations;
    vi.mocked(fetch).mockResolvedValue(jsonResponse(body));
    const result = await analyzeSightengineVideo({ bytes, receipt: receipt() });
    expect(result).toMatchObject({ verdict: "inconclusive", status: "limited", failureCode: "accounting_mismatch" });
    expect(result.persistentRuns[0].sampleIndices).toHaveLength(8);
    expect(result.coverage.complete).toBe(false);
  });

  it("rejects a returned frame count beyond the declared-interval reservation", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(payload(Array(16).fill(0.99), Array.from({ length: 16 }, (_, index) => index * 250))));
    const result = await analyzeSightengineVideo({ bytes, receipt: receipt() });
    expect(result).toMatchObject({ verdict: "inconclusive", failureCode: "accounting_mismatch", request: { operations: 80 } });
    expect(result.persistentRuns[0].sampleIndices).toHaveLength(16);
  });

  it("never turns absent, invalid, missing-tail or duplicate results into a negative", async () => {
    const malformedRequest = payload();
    delete (malformedRequest.request as Partial<typeof malformedRequest.request>).timestamp;
    for (const body of [
      payload([]), { status: "success", request: { id: "x", timestamp: 1, operations: 0 }, data: {} },
      payload([null, 0, 0, 0, 0, 0, 0, 0]), payload(Array(8).fill(0), [0, 500, 1000, 1000, 2000, 2500, 3000, 3500]),
      payload(Array(6).fill(0)), malformedRequest,
    ]) {
      vi.mocked(fetch).mockResolvedValue(jsonResponse(body));
      const result = await analyzeSightengineVideo({ bytes, receipt: receipt() });
      expect(result.verdict).toBe("inconclusive");
      expect(result.coverage.complete).toBe(false);
      expect(sightengineEvidenceSchema.safeParse(result).success).toBe(true);
    }
  }, 10_000);

  it("rejects malformed JSON and caps both declared and streamed response bytes", async () => {
    for (const response of [
      new Response("{bad json synthetic-api-secret"),
      new Response("{}", { headers: { "content-length": "1048577" } }),
      new Response(new Uint8Array(1_048_577)),
    ]) {
      vi.mocked(fetch).mockResolvedValue(response);
      const result = await analyzeSightengineVideo({ bytes, receipt: receipt() });
      expect(result.verdict).toBe("inconclusive");
      expect(["malformed_response", "response_too_large"]).toContain(result.failureCode);
      expect(JSON.stringify(result)).not.toContain("synthetic-api-secret");
    }
  });

  it("enforces the 120-second wall deadline across upload and response reading", async () => {
    vi.useFakeTimers();
    vi.mocked(fetch).mockImplementation(() => new Promise(() => undefined));
    const pendingUpload = analyzeSightengineVideo({ bytes, receipt: receipt() });
    await vi.advanceTimersByTimeAsync(121_000);
    expect(await pendingUpload).toMatchObject({ verdict: "inconclusive", failureCode: "timeout" });
    let bodyController: ReadableStreamDefaultController<Uint8Array>;
    vi.mocked(fetch).mockResolvedValue(new Response(new ReadableStream({ start(controller) { bodyController = controller; } })));
    const pendingBody = analyzeSightengineVideo({ bytes, receipt: receipt() });
    await vi.advanceTimersByTimeAsync(120_000);
    expect(await pendingBody).toMatchObject({ verdict: "inconclusive", failureCode: "timeout" });
    bodyController!.close();
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("allows two concurrent scans and queues additional submissions", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "performance"] });
    const starts: number[] = [];
    vi.mocked(fetch).mockImplementation(async () => {
      starts.push(performance.now());
      await new Promise(resolve => setTimeout(resolve, 900));
      return jsonResponse(payload());
    });
    const requests = [1, 2, 3].map(() => analyzeSightengineVideo({ bytes, receipt: receipt() }));
    await vi.advanceTimersByTimeAsync(899);
    expect(starts).toEqual([0, 0]);
    await vi.advanceTimersByTimeAsync(1);
    expect(starts).toEqual([0, 0, 900]);
    await vi.advanceTimersByTimeAsync(900);
    expect((await Promise.all(requests)).every(result => result.status === "complete")).toBe(true);
  });
});
