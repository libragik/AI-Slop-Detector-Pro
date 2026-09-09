import { randomUUID } from "node:crypto";

import { env } from "@/lib/config/env";
import { findCachedAnalysis, saveCachedAnalysis } from "./cache";
import { inspectC2pa, provenanceUnavailableForUrlOnly } from "./c2pa";
import { analyzeVideoWithGemini, withGeminiUploadedFile } from "./gemini";
import { assertFreshScanAllowed, runWithAnalysisConcurrency } from "./guard";
import { downloadSocialVideo, downloadYoutubeVideo, saveUploadedVideo, verifyYoutubeDuration, type TemporaryMedia } from "./media";
import { analyzeSightengineVideo, isSightengineConfigured } from "./sightengine";
import type { SightengineEvidence } from "./sightengine-types";
import { applySpecialistEvidence } from "./specialist-decision";
import { aggregateScore } from "./scoring";
import type {
  AnalysisResult,
  NormalizedVideoUrl,
  ProvenanceAnalysis,
  VideoAnalysis,
  YoutubeContext,
} from "./types";
import { normalizeVideoUrl } from "./url";
import { analyzeYoutubeContext } from "./youtube";
import { analyzerCacheVersion, detectorFingerprint } from "./fingerprint";
import type { MediaReceipt, SocialMediaContext } from "./media";

const inFlight = new Map<string, Promise<AnalysisResult>>();

export async function inspectGeminiMedia(media: TemporaryMedia): Promise<VideoAnalysis> {
  const controller = new AbortController();
  // Large files need time to stream to both providers. Reserve five seconds for
  // cleanup inside the lifecycle, without extending individual inference calls.
  const largeFile = media.receipt.sizeBytes >= 50_000_000;
  const timer = setTimeout(() => controller.abort(), largeFile ? 595_000 : 175_000);
  try {
    return await withGeminiUploadedFile(media.filePath, media.mimeType,
      file => analyzeVideoWithGemini({ ...file, ...media.receipt }, controller.signal), controller.signal,
      { uploadTimeoutMs: largeFile ? Math.max(env.geminiHttpTimeoutMs, 300_000) : env.geminiHttpTimeoutMs });
  } finally {
    clearTimeout(timer);
  }
}

export async function inspectMedia(media: TemporaryMedia) {
  const specialist = async (): Promise<SightengineEvidence | null> => {
    if (!env.sightengineEnabled || !isSightengineConfigured()) return null;
    return analyzeSightengineVideo({ filePath: media.filePath, receipt: media.receipt });
  };
  // Each provider has its own deadline. Retain the queue slot and local media
  // until every branch settles, even when another branch fails immediately.
  const [provenance, video, specialistEvidence] = await Promise.allSettled([
    inspectC2pa(media.filePath),
    inspectGeminiMedia(media),
    specialist(),
  ]);
  if (provenance.status === "rejected") throw provenance.reason;
  if (specialistEvidence.status === "rejected") throw specialistEvidence.reason;
  if (video.status === "rejected" && specialistEvidence.value?.status !== "complete") throw video.reason;
  const unavailable: VideoAnalysis = {
    // Required legacy score field is a placeholder, never a returned model score.
    aiLikelihood: 0, visualClassification: "inconclusive", visualAssessment: "inconclusive",
    audioAssessment: "inconclusive", identityManipulation: "inconclusive", contentType: "unknown",
    summary: "Gemini's review could not complete. The Sightengine findings remain available.",
    suspiciousMoments: [], evidenceAgainstAi: [], alternativeExplanations: [],
    limitations: ["Gemini did not return a usable review or score for this video."],
    agenticProcessingObserved: false, evidenceSufficiency: "insufficient", qualityIssues: [],
    inspection: { visualCoverage: "unavailable", temporalCoverage: "unknown",
      audioCoverage: media.receipt.hasAudio ? "unavailable" : "no_audio", issues: ["Gemini review unavailable."],
      reviewAgreement: "not_available", strategy: "sweep_and_review", coverageBasis: "requested_sampling_and_model_report",
      durationSeconds: media.receipt.durationSeconds, passes: [] },
  };
  return { provenance: provenance.value, video: video.status === "fulfilled" ? video.value : unavailable,
    specialistEvidence: specialistEvidence.value };
}

function limitations(
  video: VideoAnalysis,
  provenance: ProvenanceAnalysis,
  youtube: YoutubeContext | null,
): string[] {
  const items = [
    "This evidence assessment is not proof of origin. Detection scores have not been calibrated into probabilities.",
    "Sampling was requested across the timeline. Completion of a model request does not independently verify that every frame was examined.",
    "No watermark or Content Credential is neutral evidence and does not show that a video is authentic.",
    ...video.limitations,
  ];
  if (env.geminiVideoProcessing === "agentic" && !video.agenticProcessingObserved) {
    items.push("Agentic processing was requested, but the returned steps did not independently confirm an agentic processing call.");
  }
  if (provenance.status === "unavailable" || provenance.status === "error") items.push(provenance.note);
  if (youtube && youtube.status !== "complete" && youtube.reason) items.push(youtube.reason);
  return [...new Set(items)];
}

export function buildResult(input: {
  source: AnalysisResult["source"];
  video: VideoAnalysis;
  provenance: ProvenanceAnalysis;
  youtube: YoutubeContext | null;
  mediaReceipt?: MediaReceipt | null;
  socialContext?: SocialMediaContext | null;
  specialistEvidence?: SightengineEvidence | null;
}): AnalysisResult {
  const score = applySpecialistEvidence(aggregateScore({
    video: input.video,
    provenance: input.provenance,
    metadata: input.youtube?.metadata,
    comments: input.youtube?.comments,
    disclosure: input.socialContext ? {
      disclosed: input.socialContext.disclosureReasons.length > 0, reasons: input.socialContext.disclosureReasons,
    } : null,
  }), input.specialistEvidence ?? null);
  return {
    id: randomUUID(),
    source: input.source,
    ...score,
    videoAnalysis: input.video,
    specialistEvidence: input.specialistEvidence ?? null,
    provenance: input.provenance,
    youtube: input.youtube,
    analyzedAt: new Date().toISOString(),
    analyzerVersion: analyzerCacheVersion(),
    detectorFingerprint: detectorFingerprint(),
    mediaReceipt: input.mediaReceipt ?? null,
    socialContext: input.socialContext ?? null,
    model: env.geminiModel,
    videoProcessing: env.geminiVideoProcessing,
    cacheHit: false,
    limitations: limitations(input.video, input.provenance, input.youtube),
  };
}

async function analyzeFreshUrl(source: NormalizedVideoUrl): Promise<AnalysisResult> {
  if (source.platform === "youtube" && !(env.sightengineEnabled && isSightengineConfigured())) {
    // This metadata-only guard must complete before either Gemini interaction.
    // It downloads no audiovisual content and works without a YouTube API key.
    const durationSeconds = await verifyYoutubeDuration(source);
    // Comments never enter the visual prompt. These independent passes only meet
    // in the transparent score aggregator after each result is complete.
    const [video, youtube] = await Promise.all([
      analyzeVideoWithGemini({ uri: source.canonicalUrl, durationSeconds }),
      analyzeYoutubeContext(source.platformVideoId),
    ]);
    return buildResult({ source, video, provenance: provenanceUnavailableForUrlOnly(), youtube });
  }

  const media = await (source.platform === "youtube" ? downloadYoutubeVideo(source) : downloadSocialVideo(source));
  try {
    const [findings, youtube] = await Promise.all([
      inspectMedia(media),
      source.platform === "youtube" ? analyzeYoutubeContext(source.platformVideoId) : Promise.resolve(null),
    ]);
    return buildResult({ source, ...findings, youtube, mediaReceipt: media.receipt, socialContext: media.context });
  } finally {
    await media.cleanup();
  }
}

async function coalesce(
  canonicalKey: string,
  operation: () => Promise<AnalysisResult>,
): Promise<AnalysisResult> {
  const existing = inFlight.get(canonicalKey);
  if (existing) return existing;
  const promise = runWithAnalysisConcurrency(operation);
  inFlight.set(canonicalKey, promise);
  try {
    return await promise;
  } finally {
    if (inFlight.get(canonicalKey) === promise) inFlight.delete(canonicalKey);
  }
}

export async function analyzeUrl(inputUrl: string, clientKey: string, options: { fresh?: boolean } = {}): Promise<AnalysisResult> {
  const source = normalizeVideoUrl(inputUrl);
  const cached = options.fresh ? null : await findCachedAnalysis(source.canonicalKey);
  if (cached) return cached;

  const existing = inFlight.get(source.canonicalKey);
  if (existing) return existing;
  assertFreshScanAllowed(clientKey);

  const result = await coalesce(source.canonicalKey, () => analyzeFreshUrl(source));
  await saveCachedAnalysis(result);
  return result;
}

export async function analyzeUpload(file: File, clientKey: string, options: { fresh?: boolean } = {}): Promise<AnalysisResult> {
  const media = await saveUploadedVideo(file);
  const canonicalKey = `upload:${media.sha256}`;
  try {
    const cached = options.fresh ? null : await findCachedAnalysis(canonicalKey);
    if (cached) return cached;
    const existing = inFlight.get(canonicalKey);
    if (existing) return existing;
    assertFreshScanAllowed(clientKey);

    const source: AnalysisResult["source"] = {
      platform: "upload",
      platformVideoId: media.sha256,
      canonicalKey,
      canonicalUrl: null,
      inputUrl: null,
    };
    const result = await coalesce(canonicalKey, async () => {
      const findings = await inspectMedia(media);
      return buildResult({ source, ...findings, youtube: null, mediaReceipt: media.receipt });
    });
    await saveCachedAnalysis(result);
    return result;
  } finally {
    await media.cleanup();
  }
}
