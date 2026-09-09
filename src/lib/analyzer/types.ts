import type { MediaReceipt, SocialMediaContext } from "./media";
import type { SightengineEvidence } from "./sightengine-types";

export type Platform = "youtube" | "tiktok" | "instagram" | "x" | "upload";

export interface NormalizedVideoUrl {
  platform: Exclude<Platform, "upload">;
  platformVideoId: string;
  canonicalKey: string;
  canonicalUrl: string;
  inputUrl: string;
}

export type VisualClassification =
  | "likely_ai_generated"
  | "possibly_ai_generated"
  | "mixed_or_ai_edited"
  | "likely_not_ai_generated"
  | "inconclusive";

export interface SuspiciousMoment {
  timestamp: string;
  observation: string;
  severity: "low" | "medium" | "high";
  category:
    | "anatomy"
    | "text"
    | "physics"
    | "identity"
    | "temporal"
    | "lighting"
    | "audio"
    | "camera"
    | "other";
}

export interface VideoAnalysis {
  aiLikelihood: number;
  visualClassification: VisualClassification;
  visualAssessment: "generated" | "edited" | "likely_authentic" | "inconclusive";
  audioAssessment: "synthetic" | "likely_synthetic" | "likely_recorded" | "inconclusive";
  identityManipulation: "face_swap" | "lip_sync_manipulation" | "none_detected" | "inconclusive";
  contentType: "camera_footage" | "animation" | "cgi" | "mixed" | "unknown";
  summary: string;
  suspiciousMoments: SuspiciousMoment[];
  evidenceAgainstAi: string[];
  alternativeExplanations: string[];
  limitations: string[];
  agenticProcessingObserved: boolean;
  evidenceSufficiency?: "sufficient" | "limited" | "insufficient";
  qualityIssues?: string[];
  inspection?: VideoInspection;
}

export interface InspectionPass {
  kind: "sweep" | "review" | "adjudication";
  mode: "static" | "agentic";
  model: string;
  fps: number | null;
  status: "complete" | "failed";
  elapsedMs: number;
  aiLikelihood: number | null;
  classification: VisualClassification | null;
  summary: string;
  inputTokens: number | null;
  outputTokens: number | null;
  intervals: Array<{ startSeconds: number; endSeconds: number; /** Requested rate; null denotes agentic sampling. */ fps?: number | null }>;
  /** Original fields from every completed pass, before selection or filtering. */
  rawAnalysis?: Omit<VideoAnalysis, "inspection">;
  consistencyIssues?: string[];
  validForCorroboration?: boolean;
}

export interface VideoInspection {
  visualCoverage: "adequate" | "limited" | "unavailable";
  temporalCoverage: "adequate" | "limited" | "unknown";
  audioCoverage: "adequate" | "limited" | "unavailable" | "no_audio";
  issues: string[];
  invalidObservations?: boolean;
  reviewAgreement: "agree" | "resolved" | "disagree" | "not_available";
  strategy: "sweep_and_review";
  coverageBasis: "requested_sampling_and_model_report";
  durationSeconds: number | null;
  passes: InspectionPass[];
}

export interface CommentAnalysis {
  status: "complete" | "unavailable" | "comments_disabled" | "failed";
  sampleSize: number;
  commentsClaimingAi: number;
  commentsClaimingReal: number;
  creatorAdmissionFound: boolean;
  credibleSourceClaimFound: boolean;
  commentSummary: string;
  reason?: string;
}

export interface YoutubeMetadata {
  title: string | null;
  description: string | null;
  channelId: string | null;
  channelTitle: string | null;
  thumbnailUrl: string | null;
  publishedAt: string | null;
  duration: string | null;
  containsSyntheticMedia: boolean;
  hasExplicitAiDisclosure: boolean;
  disclosureReasons: string[];
}

export interface YoutubeContext {
  status: "complete" | "unavailable" | "failed";
  metadata: YoutubeMetadata | null;
  comments: CommentAnalysis;
  reason?: string;
}

export interface ProvenanceAnalysis {
  status: "found" | "not_found" | "unavailable" | "invalid" | "error";
  embedded: boolean;
  valid: boolean | null;
  trusted: boolean | null;
  indicatesGenerativeAi: boolean;
  digitalSourceTypes: string[];
  signer: string | null;
  validationMessages: string[];
  note: string;
}

export type ScoreAdjustmentSource =
  | "gemini"
  | "sightengine"
  | "c2pa"
  | "youtube_disclosure"
  | "creator_comment"
  | "creator_disclosure"
  | "public_comments";

export interface ScoreAdjustment {
  source: ScoreAdjustmentSource;
  rule: string;
  scoreBefore: number;
  scoreAfter: number;
  delta: number;
  reason: string;
}

export interface ScoreResult {
  baseScore: number;
  finalScore: number;
  verdict: "AI indicators detected" | "No clear AI indicators" | "Inconclusive" | "AI use disclosed" | "Verified AI provenance";
  confidence: "Not calibrated" | "Verified provenance";
  decisionReasons: string[];
  reviewRequired: boolean;
  assessmentStatus: "complete" | "limited" | "conflicting";
  evidenceLabel:
    | "Verified synthetic"
    | "AI indicators observed"
    | "Disclosed synthetic or altered"
    | "Likely synthetic"
    | "Mixed or AI-edited"
    | "Inconclusive"
    | "No reliable evidence of AI found";
  adjustments: ScoreAdjustment[];
}

export interface AnalysisResult extends ScoreResult {
  specialistEvidence?: SightengineEvidence | null;
  id: string;
  source: NormalizedVideoUrl | {
    platform: "upload";
    platformVideoId: string;
    canonicalKey: string;
    canonicalUrl: null;
    inputUrl: null;
  };
  videoAnalysis: VideoAnalysis;
  provenance: ProvenanceAnalysis;
  youtube: YoutubeContext | null;
  analyzedAt: string;
  analyzerVersion: string;
  model: string;
  videoProcessing: "agentic" | "static";
  cacheHit: boolean;
  limitations: string[];
  mediaReceipt: MediaReceipt | null;
  socialContext: SocialMediaContext | null;
  detectorFingerprint: string;
}
