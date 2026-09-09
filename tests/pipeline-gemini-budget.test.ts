import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TemporaryMedia } from "@/lib/analyzer/media";
import type { VideoAnalysis } from "@/lib/analyzer/types";

const mocks = vi.hoisted(() => ({ upload: vi.fn(), analyze: vi.fn(), specialist: vi.fn(), c2pa: vi.fn() }));
vi.mock("@/lib/analyzer/gemini", () => ({ withGeminiUploadedFile: mocks.upload, analyzeVideoWithGemini: mocks.analyze }));
vi.mock("@/lib/analyzer/sightengine", () => ({ analyzeSightengineVideo: mocks.specialist, isSightengineConfigured: () => true }));
vi.mock("@/lib/analyzer/c2pa", () => ({ inspectC2pa: mocks.c2pa }));
vi.mock("node:fs/promises", () => ({ readFile: async () => new Uint8Array([1, 2, 3]) }));
vi.mock("@/lib/config/env", async importOriginal => {
  const original = await importOriginal<typeof import("@/lib/config/env")>();
  return { ...original, env: { ...original.env, sightengineEnabled: true } };
});
import { inspectGeminiMedia, inspectMedia } from "@/lib/analyzer/pipeline";

const media: TemporaryMedia = {
  filePath: "/synthetic/immutable.mp4", mimeType: "video/mp4", size: 123, sha256: "a".repeat(64), context: null,
  receipt: { sha256: "a".repeat(64), durationSeconds: 5, width: 640, height: 360, fps: 24, hasAudio: false,
    sizeBytes: 123, mimeType: "video/mp4", mediaId: null, postId: null },
  cleanup: async () => undefined,
};

beforeEach(() => {
  vi.useFakeTimers();
  mocks.upload.mockReset();
  mocks.analyze.mockReset();
  mocks.specialist.mockReset();
  mocks.c2pa.mockReset().mockResolvedValue({ status: "unavailable" });
});
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

describe("entire uploaded Gemini lifecycle budget", () => {
  it("submits three-minute, 500 MB files to the specialist and retains its result after a Gemini failure", async () => {
    mocks.upload.mockRejectedValue(new Error("synthetic Gemini upload failure"));
    const specialist = { status: "complete", verdict: "persistent_ai_indicators", coverage: { complete: true } };
    mocks.specialist.mockResolvedValue(specialist);
    const large = { ...media, receipt: { ...media.receipt, sizeBytes: 500_000_000, durationSeconds: 180 } };
    const result = await inspectMedia(large);
    expect(mocks.specialist).toHaveBeenCalledWith({ filePath: large.filePath, receipt: large.receipt });
    expect(mocks.upload.mock.calls[0][4]).toEqual({ uploadTimeoutMs: 300_000 });
    expect(result.specialistEvidence).toBe(specialist);
    expect(result.video.inspection).toMatchObject({ passes: [], reviewAgreement: "not_available", visualCoverage: "unavailable" });
    expect(result.video.summary).toContain("could not complete");
    expect(result.video.visualClassification).toBe("inconclusive");
  });
  it("allows a large file to upload beyond one minute and keeps the extended lifecycle bounded", async () => {
    let signal!: AbortSignal;
    mocks.upload.mockImplementation((_path, _mime, _consume, incoming: AbortSignal) => {
      signal = incoming;
      return new Promise((_, reject) => incoming.addEventListener("abort", () => reject(new Error("large lifecycle ended")), { once: true }));
    });
    const pending = inspectGeminiMedia({ ...media, receipt: { ...media.receipt, sizeBytes: 500_000_000 } });
    const rejected = expect(pending).rejects.toThrow("large lifecycle ended");
    await vi.advanceTimersByTimeAsync(175_000);
    expect(signal.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(420_000);
    await rejected;
    expect(signal.aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });
  it("propagates cancellation into inference and waits for bounded cleanup before releasing", async () => {
    let uploadedSignal: AbortSignal;
    let cleanupFinished = false;
    mocks.upload.mockImplementation(async (_path, _mime, consume, signal) => {
      uploadedSignal = signal;
      try { return await consume({ uri: "test://ready", mimeType: "video/mp4" }); }
      finally {
        await new Promise(resolve => setTimeout(resolve, 5_000));
        cleanupFinished = true;
      }
    });
    mocks.analyze.mockImplementation((_input, signal: AbortSignal) => new Promise((_, reject) => {
      signal.addEventListener("abort", () => reject(new Error("synthetic cancelled inference")), { once: true });
    }));
    const pending = inspectGeminiMedia(media);
    let settled = false;
    pending.then(() => { settled = true; }, () => { settled = true; });
    const rejection = expect(pending).rejects.toThrow("synthetic cancelled inference");
    await vi.advanceTimersByTimeAsync(174_999);
    expect(uploadedSignal!.aborted).toBe(false);
    expect(settled).toBe(false);
    expect(mocks.analyze.mock.calls[0][1]).toBe(uploadedSignal!);
    expect(mocks.analyze.mock.calls[0][0]).toMatchObject({ uri: "test://ready", sha256: media.sha256, durationSeconds: 5 });
    await vi.advanceTimersByTimeAsync(1);
    expect(uploadedSignal!.aborted).toBe(true);
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(4_999);
    expect(cleanupFinished).toBe(false);
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await rejection;
    expect(cleanupFinished).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("clears the lifecycle timer after normal completion", async () => {
    const result = { summary: "Synthetic completed result" } as VideoAnalysis;
    mocks.upload.mockImplementation((_path, _mime, consume) => consume({ uri: "test://ready", mimeType: "video/mp4" }));
    mocks.analyze.mockResolvedValue(result);
    await expect(inspectGeminiMedia(media)).resolves.toBe(result);
    const signal = mocks.upload.mock.calls[0][3] as AbortSignal;
    expect(signal).toBe(mocks.analyze.mock.calls[0][1]);
    expect(signal.aborted).toBe(false);
    expect(vi.getTimerCount()).toBe(0);
    await vi.advanceTimersByTimeAsync(180_000);
    expect(signal.aborted).toBe(false);
  });

  it("clears the lifecycle timer after a fast upload failure", async () => {
    mocks.upload.mockRejectedValue(new Error("synthetic upload failure"));
    await expect(inspectGeminiMedia(media)).rejects.toThrow("synthetic upload failure");
    expect(mocks.analyze).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("waits for the specialist branch before propagating an immediate Gemini failure", async () => {
    const failure = new Error("synthetic upload failure");
    mocks.upload.mockRejectedValue(failure);
    let releaseSpecialist!: () => void;
    mocks.specialist.mockImplementation(() => new Promise(resolve => { releaseSpecialist = () => resolve(null); }));
    const pending = inspectMedia(media);
    let settled = false;
    pending.then(() => { settled = true; }, () => { settled = true; });
    const rejected = expect(pending).rejects.toBe(failure);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(mocks.specialist).toHaveBeenCalledOnce();
    expect(settled).toBe(false);
    releaseSpecialist();
    await rejected;
    expect(settled).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });
});
