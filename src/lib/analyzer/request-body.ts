export class RequestBodyTooLargeError extends Error {
  readonly code = "BODY_TOO_LARGE";
  readonly retryable = false;

  constructor() {
    super("The request body is too large.");
    this.name = "RequestBodyTooLargeError";
  }
}

export class MultipartBusyError extends Error {
  readonly code = "UPLOAD_BUSY";
  readonly retryable = true;

  constructor(readonly retryAfterSeconds = 5) {
    super("The upload parser is busy. Try again shortly.");
    this.name = "MultipartBusyError";
  }
}

let multipartActive = false;

function assertDeclaredLength(request: Request, maxBytes: number): void {
  const raw = request.headers.get("content-length")?.trim();
  if (!raw || !/^\d+$/.test(raw)) return;

  const length = Number(raw);
  if (!Number.isSafeInteger(length) || length > maxBytes) {
    throw new RequestBodyTooLargeError();
  }
}

function limitedBody(request: Request, maxBytes: number): ReadableStream<Uint8Array> | null {
  assertDeclaredLength(request, maxBytes);
  if (!request.body) return null;

  const reader = request.body.getReader();
  let received = 0;
  let draining = false;

  const drain = async () => {
    if (draining) return;
    draining = true;
    try {
      while (!(await reader.read()).done) {
        // Keep rejected request bytes out of memory while allowing the producer
        // to finish cleanly. The response can be returned before this completes.
      }
    } catch {
      // A disconnected client is expected after a rejected request.
    }
  };

  return new ReadableStream<Uint8Array>({
    async pull(controller) {
      try {
        const chunk = await reader.read();
        if (chunk.done) {
          controller.close();
          return;
        }

        received += chunk.value.byteLength;
        if (received > maxBytes) {
          controller.error(new RequestBodyTooLargeError());
          void drain();
          return;
        }
        controller.enqueue(chunk.value);
      } catch (error) {
        controller.error(error);
      }
    },
    cancel() {
      void drain();
    },
  });
}

function parsingResponse(request: Request, maxBytes: number): Response {
  const contentType = request.headers.get("content-type");
  const headers = contentType ? { "Content-Type": contentType } : undefined;
  return new Response(limitedBody(request, maxBytes), { headers });
}

export async function parseLimitedJson(request: Request, maxBytes: number): Promise<unknown> {
  return parsingResponse(request, maxBytes).json();
}

export async function withLimitedMultipart<T>(
  request: Request,
  maxBytes: number,
  consume: (form: FormData) => T | Promise<T>,
): Promise<T> {
  assertDeclaredLength(request, maxBytes);
  if (multipartActive) {
    throw new MultipartBusyError();
  }

  multipartActive = true;
  try {
    const form = await parsingResponse(request, maxBytes).formData();
    return await consume(form);
  } finally {
    multipartActive = false;
  }
}
