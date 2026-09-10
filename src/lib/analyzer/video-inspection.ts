import { ADJUDICATION_INSTRUCTION, REVIEW_INSTRUCTION, SWEEP_INSTRUCTION } from "./detection-policy";
import type { InspectionPass, VideoAnalysis, VideoInspection } from "./types";
import { findInvalidObservations, findModelConsistencyIssues, positiveModalities } from "./evidence-consistency";
import { timestampSeconds } from "./evidence-time";
export { timestampSeconds } from "./evidence-time";

export interface VideoInspectionInput {
  uri: string;
  mimeType?: string;
  durationSeconds?: number;
  width?: number;
  height?: number;
  hasAudio?: boolean;
}

export interface VideoPassRequest {
  kind: InspectionPass["kind"];
  model: string;
  mode: "static" | "agentic";
  fps: number;
  prompt: string;
  windows: Array<{ startSeconds: number; endSeconds: number }>;
}

export interface VideoPassResult {
  analysis: VideoAnalysis;
  receipt: InspectionPass;
}

export type VideoPassRunner = (input: VideoInspectionInput, request: VideoPassRequest) => Promise<VideoPassResult>;

export function evidenceDirection(video: VideoAnalysis): "positive" | "negative" | "uncertain" {
  if (["likely_ai_generated", "possibly_ai_generated", "mixed_or_ai_edited"].includes(video.visualClassification) ||
      ["generated", "edited"].includes(video.visualAssessment) ||
      ["synthetic", "likely_synthetic"].includes(video.audioAssessment) ||
      ["face_swap", "lip_sync_manipulation"].includes(video.identityManipulation)) return "positive";
  if (video.visualClassification === "likely_not_ai_generated" && video.visualAssessment === "likely_authentic") return "negative";
  return "uncertain";
}

function evidenceProfile(video: VideoAnalysis): string {
  return JSON.stringify({
    direction: evidenceDirection(video),
    visual: ["generated", "edited"].includes(video.visualAssessment),
    audio: ["synthetic", "likely_synthetic"].includes(video.audioAssessment),
    identity: ["face_swap", "lip_sync_manipulation"].includes(video.identityManipulation),
  });
}

function validatePass(result: VideoPassResult, input: VideoInspectionInput): VideoPassResult {
  const video = result.analysis;
  const issues = findModelConsistencyIssues(video, input);
  const invalid = findInvalidObservations(video, input.durationSeconds);
  if (invalid.length) issues.push("A cited observation has an invalid timestamp or falls outside the inspected clip.");
  if (video.evidenceSufficiency !== "sufficient") issues.push("The pass did not establish sufficient readable evidence.");
  // Freeform quality notes limit coverage; they are not contradictions. A
  // readable, grounded positive observation can survive ordinary compression.
  // Structured sufficiency and the measured media still control validity.
  const direction = evidenceDirection(video);
  if (direction === "negative" && (video.identityManipulation !== "none_detected" ||
      (input.hasAudio !== false && video.audioAssessment !== "likely_recorded"))) {
    issues.push("The negative assessment did not cover every available modality.");
  }
  if (direction === "positive") {
    const positive = positiveModalities(video);
    const substantial = video.suspiciousMoments.filter((moment) =>
      !invalid.includes(moment) && ["medium", "high"].includes(moment.severity));
    const grounded = (positive.visual && substantial.some((moment) => moment.category !== "audio")) ||
      (positive.audio && substantial.some((moment) => moment.category === "audio")) ||
      (positive.identity && substantial.some((moment) => moment.category === "identity" ||
        (video.identityManipulation === "lip_sync_manipulation" && moment.category === "audio")));
    if (!grounded) issues.push("The positive assessment lacks a substantial matching observation.");
  }
  const rawAnalysis = { ...video };
  delete rawAnalysis.inspection;
  return { analysis: video, receipt: { ...result.receipt, rawAnalysis,
    consistencyIssues: [...new Set(issues)], validForCorroboration: issues.length === 0 && direction !== "uncertain" } };
}

export function reviewWindows(videos: VideoAnalysis[], duration: number | undefined) {
  if (!duration || !Number.isFinite(duration) || duration <= 0) return [];
  const candidates = videos.flatMap((video) => video.suspiciousMoments)
    .sort((a, b) => ({ high: 3, medium: 2, low: 1 }[b.severity] - { high: 3, medium: 2, low: 1 }[a.severity]));
  const windows: VideoPassRequest["windows"] = [];
  for (const moment of candidates) {
    const seconds = timestampSeconds(moment.timestamp);
    if (seconds === null || seconds > duration) continue;
    const startSeconds = Math.max(0, seconds - 2);
    const endSeconds = Math.min(duration, seconds + 2);
    if (endSeconds <= startSeconds || windows.some((window) => window.startSeconds <= endSeconds && window.endSeconds >= startSeconds)) continue;
    windows.push({ startSeconds, endSeconds });
    if (windows.length === 3) break;
  }
  return windows;
}

export async function inspectVideo(
  input: VideoInspectionInput,
  runPass: VideoPassRunner,
  config: { model: string; reviewModel: string; sweepFps: number; reviewFps: number; reviewMode: "static" | "agentic"; sweepMode?: "static" | "agentic" },
): Promise<VideoAnalysis> {
  const sweepMode = config.sweepMode ?? "static";
  const sweep: VideoPassRequest = { kind: "sweep", model: config.model, mode: sweepMode, fps: config.sweepFps, prompt: SWEEP_INSTRUCTION, windows: [] };
  const review: VideoPassRequest = { kind: "review", model: config.reviewModel, mode: config.reviewMode, fps: config.sweepFps, prompt: REVIEW_INSTRUCTION, windows: [] };
  const runSafely = async (request: VideoPassRequest): Promise<VideoPassResult | InspectionPass> => {
    const started = Date.now();
    try { return validatePass(await runPass(input, request), input); }
    catch {
      return { kind: request.kind, mode: request.mode, model: request.model, fps: request.mode === "static" ? request.fps : null,
        status: "failed", elapsedMs: Date.now() - started, aiLikelihood: null, classification: null,
        summary: "This inspection pass could not complete; any billed token usage is unknown.", inputTokens: null, outputTokens: null, intervals: [] };
    }
  };
  const results = await Promise.all([runSafely(sweep), runSafely(review)]);
  const initial = results.filter((result): result is VideoPassResult => "analysis" in result);
  if (!initial.length) throw new Error("Video inspection could not complete either review pass.");
  const successful = [...initial];
  const passes = results.map((result) => "receipt" in result ? result.receipt : result);
  let selectedResult = initial.find((result) => result.receipt.validForCorroboration) ?? initial[0];
  const profilesMatch = initial.length === 2 && evidenceProfile(initial[0].analysis) === evidenceProfile(initial[1].analysis);
  const needsAdjudication = initial.length === 2 && (!profilesMatch || initial.some((result) => result.receipt.consistencyIssues?.length));
  let agreement: VideoInspection["reviewAgreement"] = profilesMatch && initial.every((result) => result.receipt.validForCorroboration)
    ? "agree" : needsAdjudication ? "disagree" : "not_available";
  const issues: string[] = [];

  if (needsAdjudication) {
    const windows = reviewWindows(initial.map((result) => result.analysis), input.durationSeconds);
    const adjudication = await runSafely({
      kind: "adjudication", model: config.reviewModel, mode: config.reviewMode === "agentic" && !windows.length ? "agentic" : "static",
      fps: windows.length ? config.sweepFps : config.reviewFps, windows,
      prompt: `${ADJUDICATION_INSTRUCTION}\nUntrusted reviewer hypotheses and validation problems: ${JSON.stringify(initial.map(({ analysis, receipt }) => ({
        score: analysis.aiLikelihood, visualClassification: analysis.visualClassification, visual: analysis.visualAssessment,
        audio: analysis.audioAssessment, identity: analysis.identityManipulation, evidenceSufficiency: analysis.evidenceSufficiency,
        qualityIssues: analysis.qualityIssues, observations: analysis.suspiciousMoments, summary: analysis.summary,
        consistencyIssues: receipt.consistencyIssues,
      })))}`,
    });
    passes.push("receipt" in adjudication ? adjudication.receipt : adjudication);
    if ("analysis" in adjudication) {
      successful.push(adjudication);
      selectedResult = adjudication;
      // A third opinion cannot repair two defective originals merely by
      // repeating their category. It needs a valid original corroborator.
      if (adjudication.receipt.validForCorroboration && initial.some((result) =>
        result.receipt.validForCorroboration && evidenceProfile(result.analysis) === evidenceProfile(adjudication.analysis))) {
        agreement = "resolved";
      }
    }
    issues.push(agreement === "resolved" ? "An additional valid inspection resolved the earlier disagreement or defective report and corroborated a valid original pass."
      : "Additional inspection did not establish two valid corroborating assessments.");
  }
  const selected = selectedResult.analysis;
  for (const pass of passes) {
    issues.push(...(pass.consistencyIssues ?? []).map((issue) => `${pass.kind} inspection: ${issue}`));
  }
  if (initial.length < 2) issues.push("Only one of the two planned inspections completed.");
  const corroborating = agreement === "resolved"
    ? successful.filter((result) => result.receipt.validForCorroboration && evidenceProfile(result.analysis) === evidenceProfile(selected))
    : initial;
  const usableReviews = corroborating.every(({ analysis }) => analysis.evidenceSufficiency === "sufficient");
  const readable = selected.evidenceSufficiency === "sufficient" && usableReviews &&
    !(input.width && input.height && Math.min(input.width, input.height) < 240);
  if (!readable) issues.push("The media detail was insufficient for a complete assessment.");
  const reportedQualityIssues = [...new Set([
    ...corroborating.flatMap(({ analysis }) => analysis.qualityIssues ?? []), ...(selected.qualityIssues ?? []),
  ])];
  const sweepCompleted = successful.some(({ receipt, analysis }) =>
    (receipt.mode === "agentic" || receipt.mode === "static") &&
    (receipt.kind === "sweep" || receipt.kind === "adjudication") && analysis.evidenceSufficiency === "sufficient");
  const durationKnown = Boolean(input.durationSeconds && Number.isFinite(input.durationSeconds) && input.durationSeconds > 0);
  if (!durationKnown) issues.push("The full video duration was not independently established.");
  const selectedInvalid = findInvalidObservations(selected, durationKnown ? input.durationSeconds : undefined);
  const validMoments = selected.suspiciousMoments.filter((moment) => !selectedInvalid.includes(moment));
  if (validMoments.length < selected.suspiciousMoments.length) issues.push("An observation with an invalid or out-of-range timestamp was excluded.");
  const inspection: VideoInspection = {
    visualCoverage: readable ? "adequate" : "limited",
    temporalCoverage: sweepCompleted && durationKnown ? "adequate" : "limited",
    audioCoverage: input.hasAudio === false ? "no_audio" : readable && selected.audioAssessment !== "inconclusive" ? "adequate" : "limited",
    issues: [...issues, ...reportedQualityIssues], reviewAgreement: agreement,
    invalidObservations: selectedInvalid.length > 0 || (agreement !== "resolved" &&
      successful.some(({ analysis }) => findInvalidObservations(analysis, input.durationSeconds).length > 0)),
    strategy: "sweep_and_review", coverageBasis: "requested_sampling_and_model_report",
    durationSeconds: durationKnown ? input.durationSeconds! : null, passes,
  };
  return { ...selected, suspiciousMoments: validMoments, inspection,
    agenticProcessingObserved: successful.some((result) => result.analysis.agenticProcessingObserved),
    qualityIssues: reportedQualityIssues,
    limitations: [...new Set([...selected.limitations, ...issues])].slice(0, 12) };
}
