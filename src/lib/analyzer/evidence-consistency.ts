import type { VideoAnalysis } from "./types";
import { timestampSeconds } from "./evidence-time";

export function positiveModalities(video: VideoAnalysis) {
  return {
    visual: video.visualAssessment === "generated" || video.visualAssessment === "edited" ||
      video.visualClassification === "likely_ai_generated" || video.visualClassification === "mixed_or_ai_edited",
    audio: video.audioAssessment === "synthetic" || video.audioAssessment === "likely_synthetic",
    identity: video.identityManipulation === "face_swap" || video.identityManipulation === "lip_sync_manipulation",
  };
}

export function findInvalidObservations(video: VideoAnalysis, durationSeconds?: number | null) {
  return (video.suspiciousMoments ?? []).filter((moment) => {
    const seconds = timestampSeconds(moment.timestamp);
    return seconds === null || (durationSeconds != null && seconds > durationSeconds);
  });
}

/** Validate raw model fields before selecting a result or counting corroboration. */
export function findModelConsistencyIssues(
  video: VideoAnalysis,
  context: { durationSeconds?: number | null; hasAudio?: boolean } = {},
): string[] {
  const positive = positiveModalities(video);
  const hasPositive = positive.visual || positive.audio || positive.identity;
  const duration = context.durationSeconds ?? video.inspection?.durationSeconds;
  const invalid = findInvalidObservations(video, duration);
  const substantive = (video.suspiciousMoments ?? []).filter((moment) =>
    !invalid.includes(moment) && ["medium", "high"].includes(moment.severity));
  const issues: string[] = [];
  if (!Number.isInteger(video.aiLikelihood) || video.aiLikelihood < 1 || video.aiLikelihood > 99) {
    issues.push("The model returned an invalid evidence score.");
  }
  // This band finds incompatible fields. It does not select a verdict or
  // turn an uncalibrated model score into a probability.
  // A weak scalar must not veto explicit, grounded modality findings. In the
  // live synthetic-narration control all reviewers recognized TTS but assigned
  // a low number to its camera-looking visuals. Grounding is checked separately.
  if (video.aiLikelihood >= 65 && !hasPositive && video.visualClassification === "likely_not_ai_generated") {
    issues.push("The model reported strong AI evidence while describing the visuals as unlikely to be generated.");
  }
  if (positive.visual && video.visualClassification === "likely_not_ai_generated") {
    issues.push("The visual assessment reports generation or AI editing but the visual classification says the opposite.");
  }
  if (video.visualClassification === "likely_ai_generated" && video.visualAssessment === "likely_authentic") {
    issues.push("The visual classification and the visual assessment disagree about whether the footage was generated.");
  }
  if ((positive.visual || positive.identity) && video.inspection?.visualCoverage === "unavailable") {
    issues.push("The model reports visual generation or identity manipulation although visual inspection was unavailable.");
  }
  if (positive.audio && (context.hasAudio === false || ["unavailable", "no_audio"].includes(video.inspection?.audioCoverage ?? ""))) {
    issues.push("The model reports synthetic audio although the inspection did not have audio to assess.");
  }
  if (substantive.length > 0 && !hasPositive && video.visualClassification === "likely_not_ai_generated") {
    issues.push("The report cites substantial suspicious observations but classifies the media as having no clear AI indicators.");
  }
  return issues;
}
