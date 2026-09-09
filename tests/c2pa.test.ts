import { describe, expect, it } from "vitest";
import { fileURLToPath } from "node:url";
import { analyzeC2paStore, inspectC2pa } from "@/lib/analyzer/c2pa";

const generated = "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia";
const camera = "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCapture";
function store(sourceType = camera, extra: Record<string, unknown> = {}) {
  return {
    active_manifest: "active",
    validation_state: "Trusted",
    manifests: { active: {
      title: "Recorded clip",
      assertions: [{ label: "c2pa.actions.v2", data: { actions: [{ action: "c2pa.created", digitalSourceType: sourceType }] } }],
      ...extra,
    } },
  };
}

describe("structured Content Credential interpretation", () => {
  it("verifies a real official SDK fixture without trusting its test certificate", async () => {
    const path = fileURLToPath(new URL("./fixtures/c2pa/CA.jpg", import.meta.url));
    expect(await inspectC2pa(path)).toMatchObject({
      status: "found", embedded: true, valid: true, trusted: false,
      signer: "C2PA Signer", indicatesGenerativeAi: false, digitalSourceTypes: [],
    });
  });

  it("recognizes an explicit source assertion in the active trusted manifest", () => {
    expect(analyzeC2paStore(store(generated), true)).toMatchObject({
      valid: true, trusted: true, indicatesGenerativeAi: true, digitalSourceTypes: [generated],
    });
  });

  it.each(["trainedAlgorithmicMedia", generated, "https://example.com/trainedAlgorithmicMedia"])("ignores free text in a signed title: %s", (title) => {
    expect(analyzeC2paStore(store(camera, { title }), true).indicatesGenerativeAi).toBe(false);
  });

  it("ignores ingredients, inactive manifests, and custom assertion text", () => {
    const input = store(camera, {
      ingredients: [{ title: generated, assertions: [{ digitalSourceType: generated }] }],
      assertions: [{ label: "org.example.note", data: { actions: [{ action: "c2pa.created", digitalSourceType: generated }] } }],
    });
    Object.assign(input.manifests, { old: store(generated).manifests.active });
    expect(analyzeC2paStore(input, true).indicatesGenerativeAi).toBe(false);
  });

  it.each([
    "https://example.com/trainedAlgorithmicMedia",
    "trainedAlgorithmicMedia",
    "http://cv.iptc.org/newscodes/digitalsourcetype/algorithmicallyEnhanced",
    "http://cv.iptc.org/newscodes/digitalsourcetype/compositeSynthetic",
  ])("does not equate lookalike or conventional algorithmic source %s with generative AI", (source) => {
    expect(analyzeC2paStore(store(source), true).indicatesGenerativeAi).toBe(false);
  });

  it("keeps a valid but untrusted assertion separate from verified provenance", () => {
    const input = { ...store(generated), validation_state: "Valid" };
    expect(analyzeC2paStore(input, true)).toMatchObject({ valid: true, trusted: false, indicatesGenerativeAi: true });
    expect(analyzeC2paStore({ ...input, validation_state: "Invalid" }, true)).toMatchObject({ status: "invalid", valid: false, trusted: false });
  });

  it("does not search other manifests when the active manifest is missing", () => {
    expect(analyzeC2paStore({ ...store(generated), active_manifest: "absent" }, true).indicatesGenerativeAi).toBe(false);
  });
});
