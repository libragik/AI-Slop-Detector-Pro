import type {
  CommentAnalysis,
  ProvenanceAnalysis,
  ScoreAdjustment,
  ScoreResult,
  VideoAnalysis,
  YoutubeMetadata,
} from "./types";
import { findInvalidObservations, findModelConsistencyIssues, positiveModalities } from "./evidence-consistency";

export interface ScoreInputs {
  video: VideoAnalysis;
  provenance?: Pick<ProvenanceAnalysis, "status" | "indicatesGenerativeAi" | "valid" | "trusted"> | null;
  metadata?: Pick<YoutubeMetadata, "containsSyntheticMedia" | "hasExplicitAiDisclosure"> | null;
  disclosure?: { disclosed: boolean; reasons: string[] } | null;
  comments?: Pick<
    CommentAnalysis,
    | "status"
    | "sampleSize"
    | "commentsClaimingAi"
    | "commentsClaimingReal"
    | "creatorAdmissionFound"
  > | null;
}

const clamp = (value: number) => Math.max(1, Math.min(99, Math.round(value)));

/**
 * Decide what the evidence supports. The model's number is retained unchanged
 * for evaluation; it is neither a probability nor a measure of confidence.
 * Extreme numbers never turn missing evidence into an authenticity claim.
 */
export function aggregateScore(inputs: ScoreInputs): ScoreResult {
  const video = inputs.video;
  const baseScore = clamp(Number.isFinite(video.aiLikelihood) ? video.aiLikelihood : 50);
  const adjustments: ScoreAdjustment[] = [{
    source: "gemini",
    rule: "uncalibrated_model_evidence",
    scoreBefore: baseScore,
    scoreAfter: baseScore,
    delta: 0,
    reason: "The model evidence score is retained for evaluation, not interpreted as a probability or confidence level.",
  }];

  const result = (
    verdict: ScoreResult["verdict"],
    evidenceLabel: ScoreResult["evidenceLabel"],
    assessmentStatus: ScoreResult["assessmentStatus"],
    decisionReasons: string[],
    reviewRequired = assessmentStatus !== "complete",
  ): ScoreResult => ({
    baseScore,
    finalScore: baseScore,
    verdict,
    confidence: verdict === "Verified AI provenance" ? "Verified provenance" : "Not calibrated",
    evidenceLabel,
    assessmentStatus,
    decisionReasons: [...new Set(decisionReasons)],
    reviewRequired,
    adjustments,
  });

  const recordSource = (source: ScoreAdjustment["source"], rule: string, reason: string) => {
    adjustments.push({ source, rule, scoreBefore: baseScore, scoreAfter: baseScore, delta: 0, reason });
  };

  // This flag is produced by the typed active-manifest parser. Missing,
  // invalid, and untrusted credentials must never establish origin.
  if (inputs.provenance?.status === "found" &&
      inputs.provenance.indicatesGenerativeAi === true &&
      inputs.provenance.valid === true && inputs.provenance.trusted === true) {
    const reason = "A valid, trusted Content Credential explicitly declares generative AI media in this asset's active manifest.";
    recordSource("c2pa", "verified_synthetic_provenance", reason);
    return result("Verified AI provenance", "Verified synthetic", "complete", [reason]);
  }

  const creatorAdmission = inputs.comments?.status === "complete" && inputs.comments.creatorAdmissionFound;
  if (inputs.disclosure?.disclosed || inputs.metadata?.containsSyntheticMedia ||
      inputs.metadata?.hasExplicitAiDisclosure || creatorAdmission) {
    const reason = creatorAdmission
      ? "A sampled comment from the creator explicitly discloses AI use. This is a creator disclosure, not independent forensic verification."
      : "Creator or platform metadata explicitly discloses AI use. This is a disclosure, not independent forensic verification.";
    recordSource(creatorAdmission ? "creator_comment" : inputs.disclosure?.disclosed ? "creator_disclosure" : "youtube_disclosure", "explicit_ai_disclosure", reason);
    return result("AI use disclosed", "Disclosed synthetic or altered", "complete", [
      reason,
      ...(inputs.disclosure?.disclosed ? inputs.disclosure.reasons : []),
    ]);
  }

  // Audience votes never increase, decrease, or establish detector evidence.
  if (inputs.comments?.status === "complete" && inputs.comments.sampleSize > 0) {
    recordSource("public_comments", "social_context_only", "Audience opinions are context only and do not change the assessment or model evidence score.");
  }

  const { visual: visualPositive, audio: audioPositive, identity: identityPositive } = positiveModalities(video);
  const hasPositiveAssessment = visualPositive || audioPositive || identityPositive;
  if (hasPositiveAssessment && video.aiLikelihood <= 35) {
    adjustments[0].reason += " Its low numerical value conflicts with the positive modality findings; only the cited evidence determines whether those findings are supported.";
  }
  const moments = video.suspiciousMoments ?? [];
  const invalidMoments = findInvalidObservations(video, video.inspection?.durationSeconds);
  const substantiveMoments = moments.filter((moment) =>
    !invalidMoments.includes(moment) && (moment.severity === "medium" || moment.severity === "high"));
  const visualGrounded = visualPositive && substantiveMoments.some((moment) => moment.category !== "audio");
  const audioGrounded = audioPositive && substantiveMoments.some((moment) => moment.category === "audio");
  const identityGrounded = identityPositive && substantiveMoments.some((moment) =>
    moment.category === "identity" || (video.identityManipulation === "lip_sync_manipulation" && moment.category === "audio"));
  const hasGroundedIndicator = visualGrounded || audioGrounded || identityGrounded;

  const conflicts = findModelConsistencyIssues(video);
  if (video.inspection?.reviewAgreement === "disagree") {
    conflicts.push("The completed analysis passes disagree, so the detector cannot give a settled assessment.");
  }
  if (conflicts.length > 0) return result("Inconclusive", "Inconclusive", "conflicting", conflicts);

  const inspection = video.inspection;
  const coverageAdequate = inspection?.visualCoverage === "adequate" && inspection.temporalCoverage === "adequate" &&
    (inspection.audioCoverage === "adequate" || inspection.audioCoverage === "no_audio");
  const reviewAvailable = inspection?.reviewAgreement === "agree" || inspection?.reviewAgreement === "resolved";
  const sufficient = video.evidenceSufficiency === "sufficient";
  const qualityIssues = video.qualityIssues ?? [];
  // Sufficiency and measured/structured coverage decide whether observations
  // are usable. Freeform notes such as pillarboxing or ordinary compression
  // remain visible without silently overriding the structured assessment.
  const complete = coverageAdequate && reviewAvailable && sufficient && invalidMoments.length === 0 &&
    !inspection?.invalidObservations;
  const coverageReasons: string[] = [];
  coverageReasons.push(...qualityIssues);
  if (invalidMoments.length > 0) coverageReasons.push("One or more cited observations have an invalid timestamp or fall outside the inspected clip.");
  if (inspection?.invalidObservations) coverageReasons.push("The inspection discarded observations that could not be matched to a valid moment in this clip.");
  if (!inspection) coverageReasons.push("The report does not establish what media was inspected.");
  else {
    if (!coverageAdequate) coverageReasons.push("Visual, temporal, or audio inspection coverage is limited.");
    if (!reviewAvailable) coverageReasons.push("An agreeing independent analysis pass is not available.");
    coverageReasons.push(...inspection.issues);
  }
  if (!sufficient) coverageReasons.push("The analysis does not establish sufficient evidence for a complete assessment.");

  // Matched deployment controls produced synthetic-audio findings for both TTS
  // and a documented human recording. Retain those observations, but do not
  // make an AI-origin decision from audio alone. A lip-sync label backed only
  // by an audio-category observation cannot bypass this safeguard.
  // The overall mixed classification can describe synthetic narration alone;
  // it does not by itself establish a positive visual assessment.
  const visualGroundedBeyondAudio = visualGrounded && (video.visualAssessment === "generated" ||
    video.visualAssessment === "edited" || video.visualClassification === "likely_ai_generated");
  const identityGroundedBeyondAudio = identityPositive && substantiveMoments.some((moment) => moment.category === "identity");
  const audioOnlyGrounding = audioGrounded || (identityGrounded && !identityGroundedBeyondAudio);
  if (audioOnlyGrounding && !visualGroundedBeyondAudio && !identityGroundedBeyondAudio) {
    return result("Inconclusive", "Inconclusive", "limited", [
      "The supported AI findings rely only on audio observations. Audio-origin classification has not been validated sufficiently to determine AI use on its own.",
      "The audio observations are retained for review; similar features can occur in human recordings.",
      ...coverageReasons,
    ]);
  }

  if (hasGroundedIndicator && video.evidenceSufficiency !== "insufficient") {
    const reasons: string[] = [];
    if (visualGrounded) reasons.push("The visual assessment reports generation or AI editing and cites a substantial visual observation.");
    if (audioGrounded) reasons.push("The audio assessment flags possible synthetic speech or audio and cites an audio observation. This audio-origin classification is unverified.");
    if (identityGrounded) reasons.push("The identity assessment reports face replacement or lip-sync manipulation and cites a substantial matching observation.");
    reasons.push("These are model-observed indicators, not verified authorship or a calibrated probability.");
    return result("AI indicators detected", video.visualClassification === "mixed_or_ai_edited" ? "Mixed or AI-edited" : "AI indicators observed",
      complete ? "complete" : "limited", [...reasons, ...coverageReasons]);
  }

  if (hasPositiveAssessment) {
    return result("Inconclusive", "Inconclusive", "limited", [
      hasGroundedIndicator
        ? "The model reports AI indicators but also says the evidence is insufficient. Further inspection is required."
        : "The model reports generation or manipulation without a substantial matching observation to support it.",
      ...coverageReasons,
    ]);
  }

  const consistentNegative = video.visualClassification === "likely_not_ai_generated" &&
    video.visualAssessment === "likely_authentic" &&
    (video.audioAssessment === "likely_recorded" || inspection?.audioCoverage === "no_audio") &&
    video.identityManipulation === "none_detected" && substantiveMoments.length === 0;
  if (complete && consistentNegative) {
    return result("No clear AI indicators", "No reliable evidence of AI found", "complete", [
      "The completed analysis passes agree that no clear AI indicators were observed in the inspected media.",
      "This does not establish that the clip is authentic; a convincing AI video can lack observable artifacts.",
    ]);
  }

  return result("Inconclusive", "Inconclusive", "limited", [
    "The available observations do not support a consistent conclusion about AI generation or manipulation.",
    ...coverageReasons,
  ]);
}
