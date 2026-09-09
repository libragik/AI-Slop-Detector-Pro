import { describe, expect, it } from "vitest";

import { env } from "@/lib/config/env";
import { MediaRetrievalError, verifyYoutubeDuration } from "@/lib/analyzer/media";
import type { NormalizedVideoUrl } from "@/lib/analyzer/types";

const source: NormalizedVideoUrl = {
  platform: "youtube",
  platformVideoId: "dQw4w9WgXcQ",
  canonicalKey: "youtube:dQw4w9WgXcQ",
  canonicalUrl: "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  inputUrl: "https://youtu.be/dQw4w9WgXcQ",
};

describe("verifyYoutubeDuration", () => {
  it("uses a metadata-only, no-shell-compatible yt-dlp argument list", async () => {
    let call: [string, string[], number] | undefined;
    const runner = async (command: string, args: string[], timeout: number) => {
      call = [command, args, timeout];
      return "42.5\n";
    };

    await expect(verifyYoutubeDuration(source, runner)).resolves.toBe(42.5);
    expect(call).toBeDefined();
    const [command, args, timeout] = call!;
    expect(command).toBe(env.ytDlpPath);
    expect(args).toContain("--ignore-config");
    expect(args).toContain("--skip-download");
    expect(args).not.toContain("--output");
    expect(args.at(-2)).toBe("--");
    expect(args.at(-1)).toBe(source.canonicalUrl);
    expect(timeout).toBeLessThanOrEqual(30_000);
  });

  it("fails closed when duration is missing or ambiguous", async () => {
    await expect(verifyYoutubeDuration(source, async () => "NA\n")).rejects.toBeInstanceOf(MediaRetrievalError);
    await expect(verifyYoutubeDuration(source, async () => "30\n40\n")).rejects.toThrow("could not be verified");
  });

  it("accepts the exact limit and rejects anything longer", async () => {
    await expect(
      verifyYoutubeDuration(source, async () => String(env.maxDurationSeconds)),
    ).resolves.toBe(env.maxDurationSeconds);
    await expect(
      verifyYoutubeDuration(source, async () => String(env.maxDurationSeconds + 0.001)),
    ).rejects.toThrow(`longer than ${env.maxDurationSeconds} seconds`);
  });
});
