import { describe, expect, it } from "vitest";

import { errorResponse } from "@/lib/analyzer/http";
import {
  MultipartBusyError,
  parseLimitedJson,
  RequestBodyTooLargeError,
  withLimitedMultipart,
} from "@/lib/analyzer/request-body";

describe("request body limits", () => {
  it("rejects a declared body that exceeds the limit", async () => {
    const request = new Request("http://localhost/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Content-Length": "100" },
      body: "{}",
    });

    await expect(parseLimitedJson(request, 8)).rejects.toBeInstanceOf(RequestBodyTooLargeError);
  });

  it("counts bytes when Content-Length is absent or forged", async () => {
    const lengths = [undefined, "2"];
    for (const contentLength of lengths) {
      const headers = new Headers({ "Content-Type": "application/json" });
      if (contentLength) headers.set("Content-Length", contentLength);
      const request = new Request("http://localhost/api/analyze", {
        method: "POST",
        headers,
        body: JSON.stringify({ value: "more than eight bytes" }),
      });

      await expect(parseLimitedJson(request, 8)).rejects.toBeInstanceOf(RequestBodyTooLargeError);
    }
  });

  it("counts the cumulative bytes in a chunked stream", async () => {
    const encoder = new TextEncoder();
    const chunks = [encoder.encode("12345"), encoder.encode("67890")];
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(chunk);
        controller.close();
      },
    });
    const request = new Request("http://localhost/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      duplex: "half",
    } as RequestInit & { duplex: "half" });

    await expect(parseLimitedJson(request, 8)).rejects.toBeInstanceOf(RequestBodyTooLargeError);
  });

  it("parses bodies that remain within the byte limit", async () => {
    const request = new Request("http://localhost/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ok: true }),
    });

    await expect(parseLimitedJson(request, 64)).resolves.toEqual({ ok: true });
  });

  it("enforces the counted limit while decoding multipart data", async () => {
    const form = new FormData();
    form.set("file", new File(["this payload is larger than the limit"], "clip.mp4", { type: "video/mp4" }));
    const request = new Request("http://localhost/api/analyze/upload", {
      method: "POST",
      body: form,
    });

    await expect(withLimitedMultipart(request, 16, (form) => form)).rejects.toBeInstanceOf(RequestBodyTooLargeError);
  });

  it("fails fast while another upload is being consumed", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    let activeStarted!: () => void;
    const started = new Promise<void>((resolve) => { activeStarted = resolve; });
    const request = () => {
      const form = new FormData();
      form.set("file", new File(["video"], "clip.mp4", { type: "video/mp4" }));
      return new Request("http://localhost/api/analyze/upload", { method: "POST", body: form });
    };

    const active = withLimitedMultipart(request(), 1_024, async (form) => {
      activeStarted();
      await gate;
      return form;
    });
    await started;

    await expect(withLimitedMultipart(request(), 1_024, (form) => form)).rejects.toBeInstanceOf(MultipartBusyError);
    release();
    await active;
  });

  it("maps body-limit and parser-pressure failures to stable HTTP responses", async () => {
    const tooLarge = errorResponse(new RequestBodyTooLargeError());
    expect(tooLarge.status).toBe(413);
    await expect(tooLarge.json()).resolves.toMatchObject({
      error: { code: "BODY_TOO_LARGE", retryable: false },
    });

    const busy = errorResponse(new MultipartBusyError(7));
    expect(busy.status).toBe(429);
    expect(busy.headers.get("Retry-After")).toBe("7");
    await expect(busy.json()).resolves.toMatchObject({
      error: { code: "UPLOAD_BUSY", retryable: true, retryAfter: 7 },
    });
  });
});
