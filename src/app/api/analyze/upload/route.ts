import { analyzeUpload } from "@/lib/analyzer/pipeline";
import { clientKey, errorResponse } from "@/lib/analyzer/http";
import { withLimitedMultipart } from "@/lib/analyzer/request-body";
import { env } from "@/lib/config/env";

export const runtime = "nodejs";
export const maxDuration = 900;
export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  try {
    if (!request.headers.get("content-type")?.toLowerCase().includes("multipart/form-data")) {
      return Response.json(
        { ok: false, message: "Upload a video as multipart form field 'file'.", error: { code: "INVALID_CONTENT_TYPE", message: "Upload a video as multipart form field 'file'.", retryable: false } },
        { status: 415 },
      );
    }
    return await withLimitedMultipart(request, env.maxMediaBytes + 1_048_576, async (form) => {
      const file = form.get("file");
      if (!(file instanceof File)) {
        return Response.json(
          { ok: false, message: "A video file is required.", error: { code: "FILE_REQUIRED", message: "A video file is required.", retryable: false } },
          { status: 400 },
        );
      }

      const analysis = await analyzeUpload(file, clientKey(request), { fresh: form.get("fresh") === "true" });
      return Response.json({ ok: true, analysis }, { status: 200, headers: { "Cache-Control": "no-store" } });
    });
  } catch (error) {
    return errorResponse(error);
  }
}
