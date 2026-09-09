import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => { vi.unstubAllEnvs(); vi.resetModules(); });

describe("detector cache fingerprint", () => {
  it("invalidates Gemini-only reports when specialist access or its switch changes, without including credentials", async () => {
    vi.stubEnv("SIGHTENGINE_ENABLED", "true");
    vi.stubEnv("SIGHTENGINE_API_USER", "");
    vi.stubEnv("SIGHTENGINE_API_SECRET", "");
    const before = (await import("@/lib/analyzer/fingerprint")).detectorFingerprint();
    vi.stubEnv("SIGHTENGINE_API_USER", "test-user");
    vi.stubEnv("SIGHTENGINE_API_SECRET", "test-secret");
    vi.resetModules();
    const enabled = (await import("@/lib/analyzer/fingerprint")).detectorFingerprint();
    expect(enabled).not.toBe(before);
    vi.stubEnv("SIGHTENGINE_API_SECRET", "rotated-test-secret");
    vi.resetModules();
    expect((await import("@/lib/analyzer/fingerprint")).detectorFingerprint()).toBe(enabled);
    vi.stubEnv("SIGHTENGINE_ENABLED", "false");
    vi.resetModules();
    expect((await import("@/lib/analyzer/fingerprint")).detectorFingerprint()).toBe(before);
  });
  it("changes when any model or sampling configuration changes", async () => {
    vi.stubEnv("GEMINI_MODEL", "model-a");
    vi.stubEnv("GEMINI_REVIEW_MODEL", "review-a");
    vi.stubEnv("GEMINI_SWEEP_FPS", "2");
    vi.stubEnv("GEMINI_REVIEW_FPS", "6");
    let previous = (await import("@/lib/analyzer/fingerprint")).detectorFingerprint();
    for (const [name, value] of [["GEMINI_MODEL", "model-b"], ["GEMINI_REVIEW_MODEL", "review-b"],
      ["GEMINI_SWEEP_FPS", "4"], ["GEMINI_REVIEW_FPS", "8"]]) {
      vi.stubEnv(name, value); vi.resetModules();
      const next = (await import("@/lib/analyzer/fingerprint")).detectorFingerprint();
      expect(next).not.toBe(previous);
      previous = next;
    }
  });
  it("does not expose keys and uses the detector policy even when an old deployment version is set", async () => {
    vi.stubEnv("ANALYZER_VERSION", "mvp-1");
    vi.stubEnv("GEMINI_API_KEY", "test-private-key");
    const fingerprint = await import("@/lib/analyzer/fingerprint");
    const version = fingerprint.analyzerCacheVersion();
    expect(version).toMatch(/^evidence-2\.[0-9]+:[a-f0-9]{24}$/);
    expect(version).not.toContain("test-private-key");
    const first = fingerprint.detectorFingerprint();
    vi.stubEnv("GEMINI_API_KEY", "another-test-key"); vi.resetModules();
    expect((await import("@/lib/analyzer/fingerprint")).detectorFingerprint()).toBe(first);
  });
});
