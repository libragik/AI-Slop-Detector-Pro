import { env } from "@/lib/config/env";
import type { ProvenanceAnalysis } from "./types";

const GENERATIVE_SOURCE_TYPES = new Set([
  "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia",
  "http://cv.iptc.org/newscodes/digitalsourcetype/compositeWithTrainedAlgorithmicMedia",
]);

function collectStrings(value: unknown, output: string[] = []): string[] {
  if (typeof value === "string") output.push(value);
  else if (Array.isArray(value)) value.forEach((item) => collectStrings(item, output));
  else if (value && typeof value === "object") Object.values(value).forEach((item) => collectStrings(item, output));
  return output;
}

function activeManifestSourceTypes(store: unknown): string[] {
  if (!store || typeof store !== "object") return [];
  const root = store as {
    active_manifest?: unknown;
    manifests?: Record<string, { assertions?: unknown }>;
  };
  if (typeof root.active_manifest !== "string") return [];
  const assertions = root.manifests?.[root.active_manifest]?.assertions;
  if (!Array.isArray(assertions)) return [];
  const results = new Set<string>();
  for (const assertion of assertions) {
    if (!assertion || !["c2pa.actions", "c2pa.actions.v2"].includes(assertion.label)) continue;
    const actions = assertion.data?.actions;
    if (!Array.isArray(actions)) continue;
    for (const action of actions) {
      // A title, ingredient, custom assertion, or lookalike URI is not a
      // declaration about this asset. Only interpret the defined source field
      // of an action in the active manifest's recognized actions assertion.
      if (action && typeof action.action === "string" && action.action.length > 0 &&
          GENERATIVE_SOURCE_TYPES.has(action.digitalSourceType)) {
        results.add(action.digitalSourceType);
      }
    }
  }
  return [...results];
}

function findValidationMessages(store: unknown): string[] {
  if (!store || typeof store !== "object") return [];
  const root = store as Record<string, unknown>;
  const candidates = [root.validation_status, root.validationStatus];
  return collectStrings(candidates).filter(Boolean).slice(0, 30);
}

function findSigner(store: unknown): string | null {
  if (!store || typeof store !== "object") return null;
  const root = store as {
    active_manifest?: string | null;
    manifests?: Record<string, { signature_info?: { issuer?: string | null; common_name?: string | null } | null }>;
  };
  const signature = root.active_manifest ? root.manifests?.[root.active_manifest]?.signature_info : null;
  return signature?.common_name ?? signature?.issuer ?? null;
}

const unavailable = (status: ProvenanceAnalysis["status"], note: string): ProvenanceAnalysis => ({
  status,
  embedded: false,
  valid: null,
  trusted: null,
  indicatesGenerativeAi: false,
  digitalSourceTypes: [],
  signer: null,
  validationMessages: [],
  note,
});

export function analyzeC2paStore(store: unknown, embedded: boolean): ProvenanceAnalysis {
  const digitalSourceTypes = activeManifestSourceTypes(store);
  const validationMessages = findValidationMessages(store);
  const validationState = store && typeof store === "object"
    ? (store as { validation_state?: unknown }).validation_state : null;
  return {
    status: validationState === "Invalid" ? "invalid" : "found",
    embedded,
    valid: validationState === "Valid" || validationState === "Trusted",
    trusted: validationState === "Trusted",
    indicatesGenerativeAi: digitalSourceTypes.length > 0,
    digitalSourceTypes,
    signer: findSigner(store),
    validationMessages,
    note: digitalSourceTypes.length > 0
      ? "An action in the active Content Credential declares generative AI media. It affects the assessment only when signature and trust validation both succeed."
      : "A Content Credential was found without an explicit generative AI source declaration in the active manifest. Ingredient history and conventional algorithmic enhancement do not establish AI generation of this clip.",
  };
}

export async function inspectC2pa(filePath: string): Promise<ProvenanceAnalysis> {
  if (!env.c2paEnabled) return unavailable("unavailable", "C2PA inspection is disabled.");

  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    const deadline = new Promise<never>((_, reject) => {
      timer = setTimeout(() => reject(new Error("Content Credential inspection deadline exceeded")), 10_000);
    });
    const inspection = async () => {
      const { Reader } = await import("@contentauth/c2pa-node");
      const reader = await Reader.fromAsset(
        { path: filePath },
        {
          verify: {
            verify_after_reading: true,
            verify_trust: true,
            ocsp_fetch: false,
            remote_manifest_fetch: false,
          },
        },
      );
      if (!reader) {
        return unavailable("not_found", "No embedded Content Credential was found. Its absence is neutral evidence.");
      }
      return analyzeC2paStore(reader.json(), reader.isEmbedded());
    };
    // The native reader exposes no cancellation API. Bound report latency;
    // late completion cannot alter this report or establish provenance.
    return await Promise.race([inspection(), deadline]);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (/no manifest|manifest.*not found|jumbf.*not found|not.*c2pa/i.test(message)) {
      return unavailable("not_found", "No Content Credential was found. Its absence is neutral evidence.");
    }
    return unavailable("error", "Content Credential inspection failed; the failure did not affect the score.");
  } finally {
    if (timer) clearTimeout(timer);
  }
}

export function provenanceUnavailableForUrlOnly(): ProvenanceAnalysis {
  return unavailable(
    "unavailable",
    "C2PA inspection requires a media file. The YouTube video was sent directly to Gemini and was not downloaded.",
  );
}
