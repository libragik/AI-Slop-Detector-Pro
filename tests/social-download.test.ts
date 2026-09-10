import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { errorResponse } from "@/lib/analyzer/http";
import { downloadSocialVideo, MediaRetrievalError } from "@/lib/analyzer/media";
import type { NormalizedVideoUrl } from "@/lib/analyzer/types";
import { normalizeVideoUrl } from "@/lib/analyzer/url";
import { env } from "@/lib/config/env";

describe("social download boundary", () => {
  it("passes only the canonical X URL to a bounded, config-free yt-dlp invocation", async () => {
    const source = normalizeVideoUrl(
      "https://mobile.twitter.com/some_person/status/1893456789012345678?utm_source=private",
    );
    let invocation: { command: string; args: string[]; timeoutMs: number } | undefined;
    let preflight: { args: string[]; timeoutMs: number } | undefined;

    await expect(
      downloadSocialVideo(
        source,
        async (command, args, timeoutMs) => {
          invocation = { command, args, timeoutMs };
          throw new MediaRetrievalError("Test stopped after command capture.");
        },
        async (_command, args, timeoutMs) => {
          preflight = { args, timeoutMs };
          return JSON.stringify({ extractor: "twitter", extractorKey: "Twitter", id: "1893456789012345678", displayId: "1893456789012345678" });
        },
      ),
    ).rejects.toThrow("Test stopped after command capture.");

    expect(preflight?.timeoutMs).toBeLessThanOrEqual(15_000);
    expect(preflight?.args).toContain("--skip-download");
    expect(preflight?.args.slice(-2)).toEqual([
      "--",
      "https://x.com/i/status/1893456789012345678",
    ]);
    expect(invocation).toBeDefined();
    expect(invocation?.command).not.toBe("");
    expect(invocation?.timeoutMs).toBeGreaterThan(0);
    expect(invocation?.args).toContain("--ignore-config");
    expect(invocation?.args).toContain("--no-cache-dir");
    expect(invocation?.args).toContain("--no-playlist");
    expect(invocation?.args).toContain("--use-extractors");
    expect(invocation?.args).toContain("twitter");
    expect(invocation?.args.slice(-2)).toEqual([
      "--",
      "https://x.com/i/status/1893456789012345678",
    ]);
    expect(invocation?.args.join(" ")).not.toContain("some_person");
    expect(invocation?.args.join(" ")).not.toContain("private");
  });

  it("allocates up to 30s preflight inspection timeout for TikTok videos", async () => {
    const source = normalizeVideoUrl(
      "https://www.tiktok.com/@yasirali.1919/video/7682866320139898119?is_from_webapp=1",
    );
    let preflight: { args: string[]; timeoutMs: number } | undefined;

    await expect(
      downloadSocialVideo(
        source,
        async () => {
          throw new MediaRetrievalError("Test stopped after command capture.");
        },
        async (_command, args, timeoutMs) => {
          preflight = { args, timeoutMs };
          return JSON.stringify({ extractor: "tiktok", extractorKey: "TikTok", id: "7682866320139898119" });
        },
      ),
    ).rejects.toThrow("Test stopped after command capture.");

    expect(preflight?.timeoutMs).toBe(30_000);
    expect(preflight?.args).toContain("--skip-download");
    expect(preflight?.args.slice(-2)).toEqual([
      "--",
      "https://www.tiktok.com/@_/video/7682866320139898119",
    ]);
  });

  it("rejects an X outbound-article Generic fallback before any download", async () => {
    const source = normalizeVideoUrl("https://x.com/NASA/status/2040565815083225472");
    let downloadInvoked = false;
    let preflightArgs: string[] | undefined;

    await expect(
      downloadSocialVideo(
        source,
        async () => {
          downloadInvoked = true;
        },
        async (_command, args) => {
          preflightArgs = args;
          return "html5\tHTML5MediaEmbed\texternal-article-media\n";
        },
      ),
    ).rejects.toThrow("does not contain a directly downloadable X video");

    expect(downloadInvoked).toBe(false);
    expect(preflightArgs).toContain("--skip-download");
    expect(preflightArgs).not.toContain("--output");
    expect(preflightArgs?.slice(-2)).toEqual([
      "--",
      "https://x.com/i/status/2040565815083225472",
    ]);
  });

  it("rejects Twitter metadata for a different status ID", async () => {
    const source = normalizeVideoUrl("https://x.com/i/status/1893456789012345678");
    let downloadInvoked = false;

    await expect(
      downloadSocialVideo(
        source,
        async () => {
          downloadInvoked = true;
        },
        async () => "twitter\tTwitter\t1111111111111111111\n",
      ),
    ).rejects.toThrow("does not contain a directly downloadable X video");
    expect(downloadInvoked).toBe(false);
  });

  it.each([
    [
      "TikTok /t/",
      "https://www.tiktok.com/t/ZSrAb_12-/?share_app_id=private",
      "https://www.tiktok.com/t/ZSrAb_12-/",
    ],
    [
      "Instagram Reel share",
      "https://www.instagram.com/share/reel/BAabcdef123/?igsh=private",
      "https://www.instagram.com/share/reel/BAabcdef123/",
    ],
  ])("revalidates the canonical %s redirect before yt-dlp", async (_label, input, canonical) => {
    let args: string[] | undefined;
    await expect(
      downloadSocialVideo(normalizeVideoUrl(input), async (_command, commandArgs) => {
        args = commandArgs;
        throw new MediaRetrievalError("Test stopped after command capture.");
      }, async () => JSON.stringify({
        extractor: input.includes("instagram") ? "instagram" : "tiktok",
        extractorKey: input.includes("instagram") ? "Instagram" : "TikTok",
        id: "1234567890",
      })),
    ).rejects.toThrow("Test stopped after command capture.");

    expect(args?.slice(-2)).toEqual(["--", canonical]);
    expect(args?.join(" ")).not.toContain("private");
  });

  it("rejects a forged source object before starting yt-dlp", async () => {
    const forged: NormalizedVideoUrl = {
      platform: "x",
      platformVideoId: "1893456789012345678",
      canonicalKey: "x:1893456789012345678",
      canonicalUrl: "https://example.com/internal-resource",
      inputUrl: "https://example.com/internal-resource",
    };
    let invoked = false;

    await expect(
      downloadSocialVideo(forged, async () => {
        invoked = true;
      }),
    ).rejects.toThrow("failed validation");
    expect(invoked).toBe(false);
  });

  it("returns a safe, actionable API error when Instagram says a post is unavailable", async () => {
    const directory = await mkdtemp(join(tmpdir(), "ai-slop-yt-dlp-test-"));
    const isWin = process.platform === "win32";
    const executable = join(directory, isWin ? "fake-yt-dlp.cmd" : "fake-yt-dlp");
    const originalPath = env.ytDlpPath;
    if (isWin) {
      await writeFile(
        executable,
        "@echo ERROR: [Instagram] Instagram sent an empty media response. source=https://instagram.com/reel/private?token=do-not-leak 1>&2\r\n@exit /b 1\r\n",
      );
    } else {
      await writeFile(
        executable,
        "#!/bin/sh\nprintf '%s\\n' 'ERROR: [Instagram] Instagram sent an empty media response. source=https://instagram.com/reel/private?token=do-not-leak' >&2\nexit 1\n",
        { mode: 0o700 },
      );
    }
    (env as { ytDlpPath: string }).ytDlpPath = executable;

    let failure: unknown;
    try {
      await downloadSocialVideo(normalizeVideoUrl("https://instagram.com/reel/C9_aBcD12/"));
    } catch (error) {
      failure = error;
    } finally {
      (env as { ytDlpPath: string }).ytDlpPath = originalPath;
      await rm(directory, { recursive: true, force: true });
    }

    expect(failure).toBeInstanceOf(MediaRetrievalError);
    const response = errorResponse(failure);
    const payload = await response.json();
    expect(response.status).toBe(422);
    expect(payload).toMatchObject({
      ok: false,
      error: {
        code: "MEDIA_RETRIEVAL_FAILED",
        message: "This Instagram post is unavailable to the scanner. It may be private, deleted, or the share link may have expired. If you can still view it, save the video and upload the file instead.",
        retryable: true,
      },
    });
    expect(JSON.stringify(payload)).not.toContain("instagram.com/reel/private");
    expect(JSON.stringify(payload)).not.toContain("do-not-leak");
    expect(JSON.stringify(payload)).not.toContain("[Instagram]");
  }, 15_000);
});
