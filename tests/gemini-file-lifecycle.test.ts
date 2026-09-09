import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const files = vi.hoisted(() => ({ get: vi.fn(), delete: vi.fn() }));
vi.mock("@google/genai", () => ({ GoogleGenAI: class { files = files; } }));
vi.mock("node:fs", () => ({ openAsBlob: async () => new Blob(["synthetic"]) }));
vi.mock("@/lib/config/env", () => ({
  requireGeminiApiKey: () => "test-only-key",
  env: { geminiFileTimeoutMs: 1_000, geminiFilePollMs: 200, geminiHttpTimeoutMs: 60_000, geminiRetryMax: 0 },
}));
import { withGeminiUploadedFile } from "@/lib/analyzer/gemini";

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
  vi.spyOn(console, "warn").mockImplementation(() => undefined);
  vi.stubGlobal("fetch", vi.fn(async (_url, options) => options.headers["X-Goog-Upload-Command"] === "start"
    ? new Response(null, { headers: { "x-goog-upload-url": "https://generativelanguage.googleapis.com/upload/session" } })
    : new Response(JSON.stringify({ file: { name: "files/test" } }), { headers: { "x-goog-upload-status": "final" } })));
  files.get.mockReset();
  files.delete.mockReset().mockResolvedValue({});
});
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("Gemini file lifecycle deadlines", () => {
  it("uses the remaining processing budget for every read and a short cleanup deadline", async () => {
    files.get.mockResolvedValueOnce({ state: "PROCESSING" }).mockResolvedValueOnce({ state: "ACTIVE", uri: "gs://test" });
    const consume = vi.fn().mockResolvedValue("report");
    const pending = withGeminiUploadedFile("/temporary/opaque.mp4", "video/mp4", consume);
    await vi.advanceTimersByTimeAsync(200);
    await expect(pending).resolves.toBe("report");
    expect(files.get.mock.calls.map(([request]) => request.config.httpOptions.timeout)).toEqual([1_000, 800]);
    expect(files.get.mock.calls[0][0].config.abortSignal).toBeInstanceOf(AbortSignal);
    expect(files.delete.mock.calls[0][0].config.httpOptions.timeout).toBe(5_000);
    expect(consume).toHaveBeenCalledOnce();
  });

  it("does not start another status request after the processing deadline", async () => {
    files.get.mockImplementation(async () => {
      vi.setSystemTime(900);
      return { state: "PROCESSING" };
    });
    const consume = vi.fn();
    const pending = withGeminiUploadedFile("/temporary/opaque.mp4", "video/mp4", consume);
    const rejected = expect(pending).rejects.toThrow("file processing timed out");
    await vi.advanceTimersByTimeAsync(200);
    await rejected;
    expect(files.get).toHaveBeenCalledOnce();
    expect(files.delete).toHaveBeenCalledOnce();
    expect(consume).not.toHaveBeenCalled();
  });

  it("preserves the inference error and attempts cleanup when both operations fail", async () => {
    files.get.mockResolvedValue({ state: "ACTIVE", uri: "gs://test" });
    files.delete.mockRejectedValue(new Error("cleanup timeout"));
    vi.spyOn(console, "warn").mockImplementation(() => {});
    await expect(withGeminiUploadedFile("/temporary/opaque.mp4", "video/mp4", async () => {
      throw new Error("inference failed");
    })).rejects.toThrow("inference failed");
    expect(files.delete).toHaveBeenCalledOnce();
  });
});
