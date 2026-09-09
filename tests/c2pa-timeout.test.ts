import { afterEach, expect, it, vi } from "vitest";
const reader = vi.hoisted(() => ({ fromAsset: vi.fn() }));
vi.mock("@contentauth/c2pa-node", () => ({ Reader: reader }));
afterEach(() => { vi.useRealTimers(); vi.unstubAllEnvs(); vi.resetModules(); reader.fromAsset.mockReset(); });

it("returns a provenance error when the native reader never resolves, without trusting a late result", async () => {
  vi.useFakeTimers();
  vi.stubEnv("C2PA_ENABLED", "true");
  reader.fromAsset.mockImplementation(() => new Promise(() => {}));
  const { inspectC2pa } = await import("@/lib/analyzer/c2pa");
  const result = inspectC2pa("/tmp/test-video.mp4");
  await vi.advanceTimersByTimeAsync(10_000);
  expect(await result).toMatchObject({ status: "error", valid: null, trusted: null, indicatesGenerativeAi: false });
  expect(vi.getTimerCount()).toBe(0);
});

it("clears its deadline after a completed no-manifest result", async () => {
  vi.useFakeTimers();
  vi.stubEnv("C2PA_ENABLED", "true");
  reader.fromAsset.mockResolvedValue(null);
  const { inspectC2pa } = await import("@/lib/analyzer/c2pa");
  expect(await inspectC2pa("/tmp/test-video.mp4")).toMatchObject({ status: "not_found" });
  expect(vi.getTimerCount()).toBe(0);
});
