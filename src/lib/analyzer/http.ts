import { MediaRetrievalError } from "./media";
import { RateLimitError } from "./guard";
import { MultipartBusyError, RequestBodyTooLargeError } from "./request-body";
import { UnsupportedVideoUrlError } from "./url";

export function clientKey(request: Request): string {
  return (
    request.headers.get("x-real-ip") ??
    request.headers.get("x-vercel-forwarded-for")?.split(",")[0]?.trim() ??
    request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ??
    "local"
  ).slice(0, 128);
}

export function errorResponse(error: unknown): Response {
  let status = 502;
  let code = "ANALYSIS_FAILED";
  let message = "The analysis provider could not complete this scan. Please try again.";
  let retryable = true;
  let retryAfter: number | undefined;

  if (error instanceof RequestBodyTooLargeError) {
    status = 413;
    code = error.code;
    message = error.message;
    retryable = error.retryable;
  } else if (error instanceof MultipartBusyError) {
    status = 429;
    code = error.code;
    message = error.message;
    retryable = error.retryable;
    retryAfter = error.retryAfterSeconds;
  } else if (error instanceof UnsupportedVideoUrlError) {
    status = 400;
    code = error.code;
    message = error.message;
    retryable = false;
  } else if (error instanceof MediaRetrievalError) {
    status = 422;
    code = error.code;
    message = error.message;
  } else if (error instanceof RateLimitError) {
    status = 429;
    code = error.code;
    message = error.message;
    retryAfter = error.retryAfterSeconds;
  } else if (error instanceof Error && /GEMINI_API_KEY/.test(error.message)) {
    status = 503;
    code = "GEMINI_NOT_CONFIGURED";
    message = "Video analysis is not configured yet.";
  }

  const headers = new Headers({ "Content-Type": "application/json", "Cache-Control": "no-store" });
  if (retryAfter) headers.set("Retry-After", String(retryAfter));
  return Response.json(
    { ok: false, message, error: { code, message, retryable, ...(retryAfter ? { retryAfter } : {}) } },
    { status, headers },
  );
}
