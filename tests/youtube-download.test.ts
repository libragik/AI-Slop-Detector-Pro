import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { copyFile, mkdtemp, readFile, rm, stat, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { downloadYoutubeVideo, MediaRetrievalError } from "@/lib/analyzer/media";
import { normalizeVideoUrl } from "@/lib/analyzer/url";
import { env } from "@/lib/config/env";

const source = normalizeVideoUrl("https://youtu.be/abcdefghijk?si=private-token");
const metadata = (changes: Record<string, unknown> = {}) => JSON.stringify({
  extractor: "youtube", extractorKey: "Youtube", id: "abcdefghijk",
  duration: 1, isLive: false, liveStatus: "not_live", filesize: null, filesizeApprox: null,
  playlistCount: null, playlistIndex: null, ...changes,
});
let directory: string;
let fixture: string;
const originalLimits = { maxMediaBytes: env.maxMediaBytes, maxDurationSeconds: env.maxDurationSeconds };

beforeAll(async () => {
  directory = await mkdtemp(join(tmpdir(), "youtube-download-contract-"));
  fixture = join(directory, "synthetic.mp4");
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=160x96:r=12:d=1",
    "-c:v", "libx264", "-pix_fmt", "yuv420p", fixture], { timeout: 20_000 });
});
afterAll(async () => { if (directory) await rm(directory, { recursive: true, force: true }); });
afterEach(() => Object.assign(env, originalLimits));

describe("YouTube byte retrieval boundary", () => {
  it("uses a canonical URL and forces the YouTube extractor in both bounded commands", async () => {
    const invocations: Array<{ args: string[]; timeout: number; platform?: string }> = [];
    await expect(downloadYoutubeVideo(source, async (_command, args, timeout, platform) => {
      invocations.push({ args, timeout, platform });
      throw new MediaRetrievalError("Captured download");
    }, async (_command, args, timeout, platform) => {
      invocations.push({ args, timeout, platform });
      return metadata();
    })).rejects.toThrow("Captured download");
    expect(invocations).toHaveLength(2);
    for (const call of invocations) {
      expect(call.platform).toBe("youtube");
      expect(call.args).toContain("--ignore-config");
      expect(call.args).toContain("--no-cache-dir");
      expect(call.args).toContain("--no-playlist");
      expect(call.args[call.args.indexOf("--use-extractors") + 1]).toBe("youtube");
      expect(call.args.slice(-2)).toEqual(["--", "https://www.youtube.com/watch?v=abcdefghijk"]);
      expect(call.args.join(" ")).not.toMatch(/private-token|cookies|description\)j|title\)j/);
      expect(call.timeout).toBeLessThanOrEqual(env.ytDlpTimeoutMs);
    }
    expect(invocations[0].timeout).toBeLessThanOrEqual(15_000);
    expect(invocations[0].args).toContain("--skip-download");
    expect(invocations[0].args).not.toContain("--output");
    expect(invocations[1].args).toContain("--max-filesize");
    expect(invocations[1].args).toContain(`!is_live & duration<=?${env.maxDurationSeconds}`);
    expect(invocations[1].args).toContain("--no-continue");
    expect(invocations[1].args).toContain("--no-overwrites");
    expect(invocations[1].args[invocations[1].args.indexOf("--output") + 1]).toMatch(/\/video\.\%\(ext\)s$/);
  });

  it.each([
    { canonicalUrl: "http://127.0.0.1/private" },
    { canonicalUrl: "https://www.youtube.com/watch?v=abcdefghijk&token=private" },
    { canonicalKey: "youtube:wrong-id" },
    { platformVideoId: "11111111111" },
    { platform: "instagram" as const },
  ])("rejects forged source fields before any subprocess: %j", async (changes) => {
    const download = vi.fn(); const preflight = vi.fn();
    await expect(downloadYoutubeVideo({ ...source, ...changes }, download, preflight)).rejects.toBeInstanceOf(MediaRetrievalError);
    expect(download).not.toHaveBeenCalled(); expect(preflight).not.toHaveBeenCalled();
  });

  it.each([
    { extractor: "generic" }, { extractorKey: "YoutubePlaylist" }, { id: "11111111111" },
    { duration: null }, { duration: "1" }, { duration: 0 }, { duration: 181 },
    { isLive: true }, { isLive: null }, { liveStatus: "is_upcoming" }, { liveStatus: "post_live" },
    { filesize: 209_715_201 }, { filesizeApprox: 209_715_201 }, { filesize: "100" }, { filesize: -1 },
    { playlistCount: 2 }, { playlistCount: "1" }, { playlistIndex: 2 }, { playlistIndex: 1 },
  ])("fails closed on unsafe or unverified metadata before downloading: %j", async (changes) => {
    Object.assign(env, { maxMediaBytes: 209_715_200, maxDurationSeconds: 180 });
    const download = vi.fn();
    await expect(downloadYoutubeVideo(source, download, async () => metadata(changes))).rejects.toThrow("one matching, non-live video");
    expect(download).not.toHaveBeenCalled();
  });

  it.each(["", "null", "[]", "not-json", `${metadata()}\n${metadata()}`])("rejects missing or multiple metadata records", async (output) => {
    const download = vi.fn();
    await expect(downloadYoutubeVideo(source, download, async () => output)).rejects.toBeInstanceOf(MediaRetrievalError);
    expect(download).not.toHaveBeenCalled();
  });

  it("returns the exact downloaded bytes and measured receipt, without source captions", async () => {
    const bytes = await readFile(fixture);
    const media = await downloadYoutubeVideo(source, async (_command, args) => {
      await copyFile(fixture, args[args.indexOf("--output") + 1].replace("%(ext)s", "mp4"));
      return metadata({ liveStatus: "was_live" });
    }, async () => metadata({ liveStatus: "was_live" }));
    try {
      expect(await readFile(media.filePath)).toEqual(bytes);
      expect(media.sha256).toBe(createHash("sha256").update(bytes).digest("hex"));
      expect(media.context).toBeNull();
      expect(media.receipt).toMatchObject({ sha256: media.sha256, mediaId: "abcdefghijk", postId: "abcdefghijk",
        width: 160, height: 96, fps: 12, hasAudio: false, mimeType: "video/mp4", sizeBytes: bytes.length });
      expect(media.receipt.durationSeconds).toBeCloseTo(1, 1);
    } finally { await media.cleanup(); }
    await expect(stat(media.filePath)).rejects.toMatchObject({ code: "ENOENT" });
  });

  it.each([metadata({ id: "11111111111" }), metadata({ extractor: "generic" }), "", `${metadata()}\n${metadata()}`])(
    "rejects changed or missing after-download identity and cleans all temporary bytes", async (output) => {
      let file = "";
      await expect(downloadYoutubeVideo(source, async (_command, args) => {
        file = args[args.indexOf("--output") + 1].replace("%(ext)s", "mp4");
        await copyFile(fixture, file); return output;
      }, async () => metadata())).rejects.toBeInstanceOf(MediaRetrievalError);
      await expect(stat(dirname(file))).rejects.toMatchObject({ code: "ENOENT" });
    },
  );

  it.each(["extra-file", "symlink", "not-video", "oversize", "duration"]) (
    "validates actual output and cleans it after rejection: %s", async (mode) => {
      let file = "";
      if (mode === "oversize") Object.assign(env, { maxMediaBytes: 100 });
      if (mode === "duration") Object.assign(env, { maxDurationSeconds: 0.5 });
      const returned = metadata({ duration: mode === "duration" ? 0.25 : 1 });
      await expect(downloadYoutubeVideo(source, async (_command, args) => {
        file = args[args.indexOf("--output") + 1].replace("%(ext)s", "mp4");
        if (mode === "symlink") await symlink(fixture, file);
        else if (mode === "not-video") await writeFile(file, "not media");
        else await copyFile(fixture, file);
        if (mode === "extra-file") await copyFile(fixture, file + ".other.mp4");
        return returned;
      }, async () => returned)).rejects.toBeInstanceOf(MediaRetrievalError);
      await expect(stat(dirname(file))).rejects.toMatchObject({ code: "ENOENT" });
    },
  );
});
