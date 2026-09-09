import { analyzeUrl } from "@/lib/analyzer/pipeline";
import { clientKey, errorResponse } from "@/lib/analyzer/http";
import { parseLimitedJson } from "@/lib/analyzer/request-body";

export const runtime = "nodejs";
export const maxDuration = 900;
export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  try {
    if (!request.headers.get("content-type")?.toLowerCase().includes("application/json")) {
      return Response.json(
        { ok: false, message: "Send a JSON body with a video URL.", error: { code: "INVALID_CONTENT_TYPE", message: "Send a JSON body with a video URL.", retryable: false } },
        { status: 415 },
      );
    }
    const body = (await parseLimitedJson(request, 8_192)) as { url?: unknown; fresh?: unknown };
    if (typeof body.url !== "string") {
      return Response.json(
        { ok: false, message: "A video URL is required.", error: { code: "URL_REQUIRED", message: "A video URL is required.", retryable: false } },
        { status: 400 },
      );
    }

    const analysis = await analyzeUrl(body.url, clientKey(request), { fresh: body.fresh === true });
    return Response.json({ ok: true, analysis }, { status: 200, headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return errorResponse(error);
  }
}
