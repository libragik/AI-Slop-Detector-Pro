import { describe, expect, it } from "vitest";
import { captionDisclosures, parseSocialMediaContext } from "@/lib/analyzer/media-context";
import { parseMediaProbe } from "@/lib/analyzer/media";
import { normalizeVideoUrl } from "@/lib/analyzer/url";

const source = normalizeVideoUrl("https://www.instagram.com/reel/DWhqiudAoQr/");
const metadata = (overrides: Record<string, unknown> = {}) => JSON.stringify({
  extractor: "Instagram", extractorKey: "Instagram", id: "DWhqiudAoQr", playlistCount: null, playlistIndex: null, ...overrides,
});

describe("social media identity and creator context", () => {
  it("retains only verified IDs and bounded URL-free caption context", () => {
    const output = parseSocialMediaContext(metadata({ description: "AI-generated clip. https://cdn.example.com/clip?token=private\n" + "a".repeat(3_000), url: "https://private.example.com?token=secret" }), source);
    expect(output).toMatchObject({ platform: "instagram", mediaId: "DWhqiudAoQr", postId: "DWhqiudAoQr" });
    expect(output.caption?.length).toBeLessThanOrEqual(2_000);
    expect(output.disclosureReasons).toHaveLength(1);
    expect(JSON.stringify(output)).not.toContain("private");
    expect(JSON.stringify(output)).not.toContain("secret");
    expect(JSON.stringify(output)).not.toContain("https:");
  });

  it.each([
    metadata({ id: "WrongMediaID" }),
    metadata({ extractor: "generic", extractorKey: "Generic" }),
    metadata({ playlistCount: 2, playlistIndex: 1 }),
    metadata({ playlistIndex: 1 }),
    metadata() + "\n" + metadata(),
  ])("rejects mismatched or ambiguous media", (output) => {
    expect(() => parseSocialMediaContext(output, source)).toThrow();
  });

  it("resolves a share token to the media ID without persisting the token", () => {
    const share = normalizeVideoUrl("https://www.instagram.com/share/reel/SecretShareToken/");
    expect(JSON.stringify(parseSocialMediaContext(metadata(), share))).not.toContain("SecretShareToken");
  });

  it("verifies an X post using display ID separately from its media ID", () => {
    const x = normalizeVideoUrl("https://x.com/NASA/status/2040619776100147411");
    expect(parseSocialMediaContext(JSON.stringify({ extractor: "twitter", extractorKey: "Twitter", id: "7654321", displayId: "2040619776100147411", playlistIndex: 1, playlistCount: 1 }), x)).toMatchObject({ mediaId: "7654321", postId: "2040619776100147411" });
  });

  it.each(["This video is not AI-generated", "Is this AI-generated?", "Learn how to spot AI-generated videos", "AI-generated video detector tutorial", "No AI was used. #aigenerated?"])("does not treat negated or commentary text as a disclosure: %s", (caption) => {
    expect(captionDisclosures(caption)).toEqual([]);
  });
});

describe("measured media properties", () => {
  it("extracts video properties and audio presence without treating audio streams as video", () => {
    expect(parseMediaProbe(JSON.stringify({ format: { duration: "71.25" }, streams: [{ codec_type: "audio" }, { codec_type: "video", width: 1080, height: 1920, avg_frame_rate: "30000/1001" }] }))).toEqual({ durationSeconds: 71.25, width: 1080, height: 1920, fps: 30000 / 1001, hasAudio: true });
  });
  it("represents unavailable frame rate as unknown", () => {
    expect(parseMediaProbe(JSON.stringify({ format: { duration: "1" }, streams: [{ codec_type: "video", width: 320, height: 240, avg_frame_rate: "0/0" }] }))).toMatchObject({ fps: null, hasAudio: false });
  });
  it.each([{ format: { duration: "1" }, streams: [{ codec_type: "audio" }] }, { format: { duration: "NaN" }, streams: [{ codec_type: "video", width: 1, height: 1 }] }])("rejects missing video or invalid duration", (probe) => {
    expect(() => parseMediaProbe(JSON.stringify(probe))).toThrow();
  });
});
