import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { mkdtemp, open, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SightengineEvidence } from "@/lib/analyzer/sightengine-types";
import type { MediaReceipt } from "@/lib/analyzer/media-context";

// Node's timers/promises uses native timers that Vitest does not replace.
vi.mock("node:timers/promises", () => ({ setTimeout: (ms: number, value: unknown, options: { signal?: AbortSignal } = {}) =>
  new Promise((resolve, reject) => {
    options.signal?.throwIfAborted();
    const abort = () => { clearTimeout(timer); reject(new Error("aborted")); };
    const timer = setTimeout(() => { options.signal?.removeEventListener("abort", abort); resolve(value); }, ms);
    options.signal?.addEventListener("abort", abort, { once: true });
  }),
}));

const bytes = new Uint8Array([1, 2, 3]);
const receipt = (durationSeconds = 180): MediaReceipt => ({
  durationSeconds, sha256: createHash("sha256").update(bytes).digest("hex"), sizeBytes: bytes.length,
  width: 640, height: 360, fps: 24, hasAudio: false, mimeType: "video/mp4", mediaId: null, postId: null,
});
const request = { id: "req_test", timestamp: 123, operations: 0 };
const submitted = { status: "success", request, media: { id: "med_test" } };
const result = (status = "finished", duration = 180) => ({
  status: "success", request: { ...request, id: "req_poll" },
  output: { media: { id: "med_test" }, request: "req_test", data: { status, progress: 1, operations: duration * 10,
    frames: Array.from({ length: duration * 2 }, (_, i) => ({ info: { position: i * 500 }, type: { ai_generated: 0.99 } })) } },
});
const json = (body: unknown) => new Response(JSON.stringify(body));
let analyze: typeof import("@/lib/analyzer/sightengine")["analyzeSightengineVideo"];

beforeEach(async () => {
  vi.resetModules();
  vi.stubEnv("SIGHTENGINE_API_USER", "test-user"); vi.stubEnv("SIGHTENGINE_API_SECRET", "test-secret");
  vi.stubEnv("MAX_MEDIA_BYTES", "500000000"); vi.stubEnv("MAX_DURATION_SECONDS", "180");
  analyze = (await import("@/lib/analyzer/sightengine")).analyzeSightengineVideo;
  vi.stubGlobal("fetch", vi.fn());
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

describe("Sightengine long-video jobs", () => {
  it.each([60, 120, 180])("accepts %s seconds and uses final job operations rather than polling-request operations", async duration => {
    vi.useFakeTimers();
    vi.mocked(fetch).mockResolvedValueOnce(json(submitted)).mockResolvedValueOnce(json(result("finished", duration)));
    const pending = analyze({ bytes, receipt: receipt(duration) });
    await vi.advanceTimersByTimeAsync(3_000);
    expect(await pending).toMatchObject({ status: "complete", verdict: "persistent_ai_indicators",
      request: { transport: "async", upload: "direct", operations: duration * 10, pollCount: 1, jobStatus: "finished" } });
    expect(fetch).toHaveBeenCalledTimes(2);
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("https://api.sightengine.com/1.0/video/check.json");
    const form = init!.body as FormData;
    expect(form.get("interval")).toBe("0.5"); expect(form.get("max_duration")).toBe("181");
    expect(form.has("callback_url")).toBe(false);
    expect(new Uint8Array(await (form.get("media") as File).arrayBuffer())).toEqual(bytes);
  });

  it("does not treat 100% progress as finished while the job still says ongoing", async () => {
    vi.useFakeTimers();
    vi.mocked(fetch).mockResolvedValueOnce(json(submitted)).mockResolvedValueOnce(json(result("ongoing")))
      .mockResolvedValueOnce(json(result()));
    let returned: SightengineEvidence | undefined;
    const pending = analyze({ bytes, receipt: receipt() }).then(value => { returned = value; return value; });
    await vi.advanceTimersByTimeAsync(3_000);
    expect(returned).toBeUndefined();
    await vi.advanceTimersByTimeAsync(3_000);
    expect((await pending).request.pollCount).toBe(2);
  });

  it.each(["media", "request"])("rejects results for a different %s and stops only its own job", async field => {
    vi.useFakeTimers(); const wrong = result();
    if (field === "media") wrong.output.media.id = "med_someone_else";
    else wrong.output.request = "req_someone_else";
    vi.mocked(fetch).mockResolvedValueOnce(json(submitted)).mockResolvedValueOnce(json(wrong)).mockResolvedValueOnce(json({ status: "success" }));
    const pending = analyze({ bytes, receipt: receipt() }); await vi.advanceTimersByTimeAsync(3_000);
    expect(await pending).toMatchObject({ failureCode: "malformed_response", request: { stopRequested: true, stopConfirmed: true } });
    const [url, init] = vi.mocked(fetch).mock.calls[2];
    expect(url).toBe("https://api.sightengine.com/1.0/video/byid.json"); expect(init?.method).toBe("DELETE");
    expect((init?.body as URLSearchParams).get("id")).toBe("med_test");
  });

  it.each(["failure", "stopped"])("retains partial evidence for a %s job without calling it complete", async status => {
    vi.useFakeTimers();
    vi.mocked(fetch).mockResolvedValueOnce(json(submitted)).mockResolvedValueOnce(json(result(status)));
    const pending = analyze({ bytes, receipt: receipt() }); await vi.advanceTimersByTimeAsync(3_000);
    expect(await pending).toMatchObject({ status: "limited", verdict: "inconclusive", failureCode: "provider_rejected",
      request: { jobStatus: status, stopRequested: false, operations: 1800 } });
    expect((await pending).samples).toHaveLength(360);
  });

  it("bounds polling and explicitly stops its unfinished paid job on timeout", async () => {
    vi.useFakeTimers();
    vi.mocked(fetch).mockImplementation(async (_url, init) => init?.method === "DELETE"
      ? json({ status: "success" }) : init?.method === "POST" ? json(submitted) : json(result("ongoing")));
    const pending = analyze({ bytes, receipt: receipt() }); await vi.advanceTimersByTimeAsync(600_000);
    expect(await pending).toMatchObject({ failureCode: "timeout", status: "limited", request: { stopRequested: true, stopConfirmed: true } });
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe("Sightengine Upload API", () => {
  it("streams an exact 500 MB file, with no API credentials forwarded to the signed upload", async () => {
    const directory = await mkdtemp(join(tmpdir(), "sightengine-large-test-"));
    const filePath = join(directory, "opaque.mp4");
    try {
      const file = await open(filePath, "wx"); await file.truncate(500_000_000); await file.close();
      const hash = createHash("sha256"); for await (const chunk of createReadStream(filePath)) hash.update(chunk);
      const media = { ...receipt(), sizeBytes: 500_000_000, sha256: hash.digest("hex") };
      const url = `https://s3.eu-west-1.amazonaws.com/storage-eu1.sightengine.com/test?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=${"a".repeat(64)}`;
      vi.mocked(fetch).mockResolvedValueOnce(json({ ...submitted, media: { id: "med_uploaded_asset" }, upload: { url } }))
        .mockImplementationOnce(async (target, init) => {
          expect(target).toBe(url); expect(init?.method).toBe("PUT"); expect(init?.redirect).toBe("error");
          expect(init?.headers).toEqual({ "Content-Type": "video/mp4" });
          const blob = init?.body as Blob; expect(blob.size).toBe(500_000_000);
          expect(new Uint8Array(await blob.slice(-8).arrayBuffer())).toEqual(new Uint8Array(8));
          return new Response(null, { status: 200 });
        }).mockResolvedValueOnce(json(submitted)).mockResolvedValueOnce(json(result()));
      const analyzed = await analyze({ filePath, receipt: media });
      expect(analyzed).toMatchObject({ status: "complete", sourceSha256: media.sha256,
        request: { transport: "async", upload: "upload_api", operations: 1800, uploadMediaId: "med_uploaded_asset", mediaId: "med_test" } });
      const form = vi.mocked(fetch).mock.calls[2][1]!.body as FormData;
      expect(form.get("media_id")).toBe("med_uploaded_asset"); expect(form.has("media")).toBe(false);
      expect(JSON.stringify(analyzed)).not.toContain("test-secret");
    } finally { await rm(directory, { recursive: true, force: true }); }
  }, 45_000);

  it.each(["https://attacker.example/u/x", "https://storage-eu1.sightengine.com.attacker.example/u/x", "http://storage-eu1.sightengine.com/u/x",
    `https://s3.eu-west-1.amazonaws.com/someone-else/test?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=${"a".repeat(64)}`])(
    "refuses an unexpected signed-upload destination %s", async url => {
      const large = new Uint8Array(50_000_001);
      const media = { ...receipt(4), sizeBytes: large.length, sha256: createHash("sha256").update(large).digest("hex") };
      vi.mocked(fetch).mockResolvedValueOnce(json({ ...submitted, upload: { url } }));
      const analyzed = await analyze({ bytes: large, receipt: media });
      expect(analyzed.failureCode).toBe("malformed_response"); expect(fetch).toHaveBeenCalledTimes(1);
    });
});
