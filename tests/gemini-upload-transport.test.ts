import { GoogleGenAI } from "@google/genai";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/config/env", () => ({ requireGeminiApiKey: () => "offline-test-key", env: {} }));
import { uploadGeminiFile } from "@/lib/analyzer/gemini";

const origin = "https://generativelanguage.googleapis.com";
const media = new Uint8Array([0, 1, 255, 42, 9, 17]);
let directory: string;
let file: string;
let requests: Request[];

function setupResponse(url = `${origin}/upload/session?opaque=synthetic`) {
  return new Response(null, { headers: { "x-goog-upload-url": url } });
}
function finalResponse(value: unknown = { file: { name: "files/synthetic" } }) {
  return new Response(JSON.stringify(value), { headers: { "x-goog-upload-status": "final" } });
}

beforeEach(async () => {
  directory = await mkdtemp(join(tmpdir(), "gemini-offline-transport-"));
  file = join(directory, "private-origin-label.mp4");
  await writeFile(file, media);
  requests = [];
  vi.spyOn(console, "warn").mockImplementation(() => undefined);
  // This is the real installed SDK. All network traffic is intercepted here.
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = new Request(input, init);
    requests.push(request);
    return request.headers.get("x-goog-upload-command") === "start" ? setupResponse() : finalResponse();
  }));
});
afterEach(async () => { vi.unstubAllGlobals(); vi.restoreAllMocks(); await rm(directory, { recursive: true, force: true }); });

describe("abortable Gemini Files transport against the installed SDK protocol", () => {
  it("preserves the SDK default setup URL and required headers despite configured client timeout", async () => {
    const sdk = new GoogleGenAI({ apiKey: "offline-test-key", apiVersion: "v1beta",
      httpOptions: { timeout: 1_000, retryOptions: { attempts: 1 } } });
    await sdk.files.upload({ file: new Blob([media], { type: "video/mp4" }),
      config: { mimeType: "video/mp4", displayName: "video-under-review" } });
    expect(requests).toHaveLength(2);
    const sdkSetup = requests[0];
    requests = [];
    const signal = new AbortController().signal;
    await expect(uploadGeminiFile(file, "video/mp4", signal)).resolves.toEqual({ name: "files/synthetic" });
    expect(requests).toHaveLength(2);
    const [setup, transfer] = requests;
    expect(setup.url).toBe(`${origin}/upload/v1beta/files`);
    expect(setup.url).toBe(sdkSetup.url);
    for (const header of ["content-type", "x-goog-upload-protocol", "x-goog-upload-command",
      "x-goog-upload-header-content-length", "x-goog-upload-header-content-type"]) {
      expect(setup.headers.get(header)).toBe(sdkSetup.headers.get(header));
    }
    expect(await setup.json()).toEqual({ file: { mimeType: "video/mp4", displayName: "video-under-review", sizeBytes: "6" } });
    expect(setup.headers.get("x-goog-api-key")).toBe("offline-test-key");
    expect(transfer.headers.get("x-goog-api-key")).toBeNull();
    expect(transfer.headers.get("x-goog-upload-command")).toBe("upload, finalize");
    expect(transfer.headers.get("x-goog-upload-offset")).toBe("0");
    expect(new Uint8Array(await transfer.arrayBuffer())).toEqual(media);
    expect(requests.every(request => request.redirect === "error")).toBe(true);
    expect(requests.every(request => !request.url.includes("offline-test-key"))).toBe(true);
  });

  it.each(["https://untrusted.example/upload", "http://generativelanguage.googleapis.com/upload",
    "https://user:pass@generativelanguage.googleapis.com/upload", `${origin}:444/upload`, `${origin}/upload#fragment`])(
    "refuses an untrusted upload session without sending media: %s", async url => {
      vi.mocked(fetch).mockResolvedValueOnce(setupResponse(url));
      await expect(uploadGeminiFile(file, "video/mp4", new AbortController().signal)).rejects.toMatchObject({ code: "GEMINI_UPLOAD_FAILED" });
      expect(fetch).toHaveBeenCalledOnce();
    });

  it.each(["setup", "transfer"])("passes cancellation into a stalled %s transport", async stage => {
    let requestStarted!: () => void;
    const started = new Promise<void>(resolve => { requestStarted = resolve; });
    const pendingFetch = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init!.signal!.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
      requestStarted();
    }));
    vi.mocked(fetch).mockReset();
    if (stage === "transfer") vi.mocked(fetch).mockResolvedValueOnce(setupResponse());
    vi.mocked(fetch).mockImplementation(pendingFetch);
    const controller = new AbortController();
    const pending = uploadGeminiFile(file, "video/mp4", controller.signal);
    const rejected = expect(pending).rejects.toMatchObject({ name: "AbortError" });
    await started;
    controller.abort();
    await rejected;
    expect(pendingFetch.mock.calls[0][1]?.signal).toBe(controller.signal);
    expect(fetch).toHaveBeenCalledTimes(stage === "setup" ? 1 : 2);
  });

  it("rejects oversized, malformed and nonfinal completion responses without exposing body text", async () => {
    for (const response of [
      finalResponse({ file: { name: `files/${"x".repeat(65_536)}` } }),
      finalResponse({ file: { name: "files/../private" }, secret: "sensitive-provider-text" }),
      new Response("sensitive-provider-text", { status: 503 }),
      new Response("sensitive-provider-text", { headers: { "x-goog-upload-status": "active" } }),
    ]) {
      vi.mocked(fetch).mockReset().mockResolvedValueOnce(setupResponse()).mockResolvedValueOnce(response);
      await expect(uploadGeminiFile(file, "video/mp4", new AbortController().signal)).rejects.toMatchObject({
        code: "GEMINI_UPLOAD_FAILED", message: expect.not.stringContaining("sensitive-provider-text"),
      });
      expect(fetch).toHaveBeenCalledTimes(2);
    }
  });

  it("does not begin an upload when already cancelled", async () => {
    const controller = new AbortController();
    controller.abort();
    await expect(uploadGeminiFile(file, "video/mp4", controller.signal)).rejects.toMatchObject({ name: "AbortError" });
    expect(fetch).not.toHaveBeenCalled();
  });

  it("logs only a safe stage and numeric status when upload setup fails", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response("private-body-with-key-and-url", { status: 404 }));
    await expect(uploadGeminiFile(file, "video/mp4", new AbortController().signal)).rejects.toMatchObject({ status: 404 });
    expect(console.warn).toHaveBeenCalledWith("[ai-slop-detector] Gemini upload failed", {
      event: "gemini_upload_failed", stage: "setup", elapsedMs: expect.any(Number),
      errorName: "GeminiUploadError", errorCode: "GEMINI_UPLOAD_FAILED", httpStatus: 404,
    });
    const diagnostic = JSON.stringify(vi.mocked(console.warn).mock.calls);
    expect(diagnostic).not.toContain("private-");
    expect(diagnostic).not.toContain("offline-test-key");
    expect(diagnostic).not.toContain(origin);
  });

  it("does not wait for an unread cloned setup response before transferring the video", async () => {
    const setup = new Response("{}", { headers: { "x-goog-upload-url": `${origin}/upload/session` } });
    const unreadSibling = setup.clone();
    const originalCancel = setup.body!.cancel.bind(setup.body!);
    let cancellationFinished = false;
    vi.spyOn(setup.body!, "cancel").mockImplementation(reason => originalCancel(reason).then(() => { cancellationFinished = true; }));
    vi.mocked(fetch).mockResolvedValueOnce(setup).mockResolvedValueOnce(finalResponse());
    let timeout!: ReturnType<typeof setTimeout>;
    try {
      const result = await Promise.race([
        uploadGeminiFile(file, "video/mp4", new AbortController().signal),
        new Promise<never>((_resolve, reject) => { timeout = setTimeout(() => reject(new Error("upload held by unread response sibling")), 500); }),
      ]);
      expect(result).toEqual({ name: "files/synthetic" });
      expect(cancellationFinished).toBe(false);
      expect(fetch).toHaveBeenCalledTimes(2);
    } finally {
      clearTimeout(timeout);
      await unreadSibling.text();
    }
  });
});
