import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { copyFile, mkdtemp, readFile, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { inspectC2pa } from "@/lib/analyzer/c2pa";
import { downloadSocialVideo, saveUploadedVideo } from "@/lib/analyzer/media";
import { normalizeVideoUrl } from "@/lib/analyzer/url";

let directory: string;
let fixture: string;
beforeAll(async () => {
  directory = await mkdtemp(join(tmpdir(), "ai-slop-media-fixture-"));
  fixture = join(directory, "camera-test.mp4");
  // Real encoded audiovisual fixture exercises file sniffing, ffprobe, hashing,
  // and the native C2PA reader. FFmpeg is also a documented runtime requirement.
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=160x96:r=12:d=1", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", fixture], { timeout: 20_000 });
});
afterAll(async () => { if (directory) await rm(directory, { recursive: true, force: true }); });

describe("verified media receipts", () => {
  it("returns measured dimensions, duration, frame rate, audio and exact digest for an upload", async () => {
    const bytes = await readFile(fixture);
    const media = await saveUploadedVideo(new File([new Uint8Array(bytes)], "clip.mp4", { type: "video/mp4" }));
    try {
      expect(media.receipt).toMatchObject({ width: 160, height: 96, fps: 12, hasAudio: true, mimeType: "video/mp4", sizeBytes: bytes.length, mediaId: null, postId: null });
      expect(media.receipt.durationSeconds).toBeCloseTo(1, 1);
      expect(media.receipt.sha256).toBe(createHash("sha256").update(bytes).digest("hex"));
      expect(media.context).toBeNull();
      expect(await inspectC2pa(media.filePath)).toMatchObject({ status: "not_found", indicatesGenerativeAi: false });
    } finally { await media.cleanup(); }
    await expect(stat(media.filePath)).rejects.toMatchObject({ code: "ENOENT" });
  });

  it("binds social context and receipt to the downloaded media, then removes the temporary file", async () => {
    const source = normalizeVideoUrl("https://www.instagram.com/reel/DWhqiudAoQr/");
    const metadata = JSON.stringify({ extractor: "instagram", extractorKey: "Instagram", id: "DWhqiudAoQr", description: "Made with Sora. https://example.com/?token=private" });
    const media = await downloadSocialVideo(source, async (_command, args) => {
      const output = args[args.indexOf("--output") + 1].replace("%(ext)s", "mp4");
      await copyFile(fixture, output);
      return metadata;
    }, async () => metadata);
    try {
      expect(media.receipt.mediaId).toBe("DWhqiudAoQr");
      expect(media.context?.disclosureReasons).toHaveLength(1);
      expect(JSON.stringify(media.context)).not.toContain("private");
    } finally { await media.cleanup(); }
  });

  it("rejects multiple output files instead of silently selecting the largest", async () => {
    const source = normalizeVideoUrl("https://www.instagram.com/reel/DWhqiudAoQr/");
    const metadata = JSON.stringify({ extractor: "instagram", extractorKey: "Instagram", id: "DWhqiudAoQr" });
    let output = "";
    await expect(downloadSocialVideo(source, async (_command, args) => {
      output = args[args.indexOf("--output") + 1].replace("%(ext)s", "mp4");
      await copyFile(fixture, output);
      await copyFile(fixture, output + ".second.mp4");
      return metadata;
    }, async () => metadata)).rejects.toThrow("one unambiguous video");
    await expect(stat(output)).rejects.toMatchObject({ code: "ENOENT" });
  });
});
