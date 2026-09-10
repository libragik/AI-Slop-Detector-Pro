import { describe, expect, it } from "vitest";

import { normalizeVideoUrl, UnsupportedVideoUrlError } from "@/lib/analyzer/url";

describe("normalizeVideoUrl", () => {
  it.each([
    "https://www.youtube.com/shorts/dQw4w9WgXcQ?feature=share",
    "https://youtube.com/watch?v=dQw4w9WgXcQ&utm_source=test",
    "https://youtu.be/dQw4w9WgXcQ?t=12",
    "https://m.youtube.com/embed/dQw4w9WgXcQ",
  ])("normalizes YouTube variants: %s", (url) => {
    expect(normalizeVideoUrl(url)).toMatchObject({
      platform: "youtube",
      platformVideoId: "dQw4w9WgXcQ",
      canonicalKey: "youtube:dQw4w9WgXcQ",
      canonicalUrl: "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    });
  });

  it("normalizes a TikTok post and strips tracking parameters", () => {
    const result = normalizeVideoUrl("https://www.tiktok.com/@creator/video/7485960123456789012?is_from_webapp=1&share_token=private");
    expect(result).toMatchObject({
      platform: "tiktok",
      platformVideoId: "7485960123456789012",
      canonicalKey: "tiktok:7485960123456789012",
      canonicalUrl: "https://www.tiktok.com/@_/video/7485960123456789012",
      inputUrl: "https://www.tiktok.com/@_/video/7485960123456789012",
    });
    expect(JSON.stringify(result)).not.toContain("private");
  });

  it.each([
    ["https://vt.tiktok.com/ZSrAb_12-/?share_app_id=private", "vt.tiktok.com", "https://vt.tiktok.com/ZSrAb_12-"],
    ["https://vm.tiktok.com/ZSrAb_12-/", "vm.tiktok.com", "https://vm.tiktok.com/ZSrAb_12-"],
    ["https://www.tiktok.com/t/ZSrAb_12-/?lang=en", "www.tiktok.com", "https://www.tiktok.com/t/ZSrAb_12-/"],
  ])("normalizes a TikTok share redirect without following it: %s", (url, host, canonicalUrl) => {
    const result = normalizeVideoUrl(url);
    expect(result).toEqual({
      platform: "tiktok",
      platformVideoId: `share-${host}-ZSrAb_12-`,
      canonicalKey: `tiktok:share:${host}:ZSrAb_12-`,
      canonicalUrl,
      inputUrl: canonicalUrl,
    });
    expect(JSON.stringify(result)).not.toContain("private");
  });

  it.each([
    ["https://instagram.com/reel/C9_aBcD12/?igsh=tracking", "instagram:C9_aBcD12", "https://www.instagram.com/reel/C9_aBcD12/"],
    ["https://www.instagram.com/p/C9_aBcD12/", "instagram:C9_aBcD12", "https://www.instagram.com/p/C9_aBcD12/"],
    ["https://www.instagram.com/askcatgpt/reel/DcIRCXIiDhf", "instagram:DcIRCXIiDhf", "https://www.instagram.com/reel/DcIRCXIiDhf/"],
    ["https://www.instagram.com/askcatgpt/reel/DcIRCXIiDhf/?igsh=tracking", "instagram:DcIRCXIiDhf", "https://www.instagram.com/reel/DcIRCXIiDhf/"],
    ["https://www.instagram.com/@askcatgpt/reel/DcIRCXIiDhf", "instagram:DcIRCXIiDhf", "https://www.instagram.com/reel/DcIRCXIiDhf/"],
    ["https://instagram.com/creator.name/p/DcIRCXIiDhf/", "instagram:DcIRCXIiDhf", "https://www.instagram.com/p/DcIRCXIiDhf/"],
    ["https://www.instagram.com/creator_123/reels/DcIRCXIiDhf", "instagram:DcIRCXIiDhf", "https://www.instagram.com/reel/DcIRCXIiDhf/"],
  ])("normalizes Instagram media: %s", (url, key, canonicalUrl) => {
    expect(normalizeVideoUrl(url)).toMatchObject({ platform: "instagram", canonicalKey: key, canonicalUrl });
  });

  it("normalizes a genuine Instagram Reel share redirect as an opaque token", () => {
    expect(normalizeVideoUrl("https://www.instagram.com/share/reel/BAabcdef123/?igsh=private")).toEqual({
      platform: "instagram",
      platformVideoId: "share-reel-BAabcdef123",
      canonicalKey: "instagram:share:reel:BAabcdef123",
      canonicalUrl: "https://www.instagram.com/share/reel/BAabcdef123/",
      inputUrl: "https://www.instagram.com/share/reel/BAabcdef123/",
    });
  });

  it.each([
    "https://x.com/futuretools/status/1893456789012345678?s=20&t=private",
    "https://www.x.com/futuretools/status/1893456789012345678/video/1",
    "https://mobile.twitter.com/futuretools/status/1893456789012345678",
    "https://m.twitter.com/i/web/status/1893456789012345678?ref_src=tracking",
    "http://twitter.com/statuses/1893456789012345678",
  ])("normalizes X status variants by numeric ID: %s", (url) => {
    const result = normalizeVideoUrl(url);
    expect(result).toEqual({
      platform: "x",
      platformVideoId: "1893456789012345678",
      canonicalKey: "x:1893456789012345678",
      canonicalUrl: "https://x.com/i/status/1893456789012345678",
      inputUrl: "https://x.com/i/status/1893456789012345678",
    });
    expect(JSON.stringify(result)).not.toContain("private");
    expect(JSON.stringify(result)).not.toContain("futuretools");
  });

  it("accepts its own canonical X status URL", () => {
    const canonical = "https://x.com/i/status/1893456789012345678";
    expect(normalizeVideoUrl(canonical).canonicalUrl).toBe(canonical);
  });

  it.each([
    "javascript:alert(1)",
    "https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ",
    "https://evil.example/https://youtube.com/watch?v=dQw4w9WgXcQ",
    "https://user:pass@youtu.be/dQw4w9WgXcQ",
    "https://youtu.be:444/dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ/extra",
    "https://www.youtube.com/shorts/not-valid",
    "https://www.tiktok.com/@creator",
    "https://www.tiktok.com/@creator/video/123/extra",
    "https://www.tiktok.com/t/",
    "https://www.tiktok.com/t/ZSrAb_12-/extra",
    "https://foo.tiktok.com/t/ZSrAb_12-/",
    "https://vm.tiktok.com/ZSrAb_12-/extra",
    "https://www.instagram.com/explore/",
    "https://www.instagram.com/share/reel/",
    "https://www.instagram.com/share/reel/BAabcdef123/extra",
    "https://www.instagram.com/share/story/BAabcdef123/",
    "https://x.com/futuretools",
    "https://x.com/home",
    "https://x.com/futuretools/status/not-numeric",
    "https://x.com/futuretools/status/1893456789012345678/analytics",
    "https://x.com:444/futuretools/status/1893456789012345678",
    "https://x.com.evil.example/futuretools/status/1893456789012345678",
  ])("rejects unsupported or ambiguous URLs: %s", (url) => {
    expect(() => normalizeVideoUrl(url)).toThrow(UnsupportedVideoUrlError);
  });
});
