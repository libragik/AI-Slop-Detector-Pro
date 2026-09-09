import type { AnalysisResult } from "./result-report";

export const demoResult: AnalysisResult = {
  id: "demo-report",
  source: "fresh",
  platform: "youtube",
  title: "Dog drives a fire truck through a supermarket",
  thumbnailUrl: null,
  verdict: "AI indicators detected",
  confidence: "Not calibrated",
  evidenceLabel: "AI indicators observed",
  assessmentStatus: "complete",
  reviewRequired: false,
  decisionReasons: [
    "This fictional example illustrates a report where separate inspections cite consistent AI indicators.",
    "Observable indicators do not establish verified authorship or a calibrated probability.",
  ],
  visualAssessment: "generated",
  audioAssessment: "likely_recorded",
  identityManipulation: "none_detected",
  inspection: {
    visualCoverage: "adequate", temporalCoverage: "adequate", audioCoverage: "adequate",
    issues: [], reviewAgreement: "agree", strategy: "sweep_and_review",
    coverageBasis: "requested_sampling_and_model_report", durationSeconds: 15,
    passes: ["sweep", "review"].map((kind) => ({
      kind: kind as "sweep" | "review", mode: kind === "sweep" ? "static" : "agentic",
      model: "Illustrative example", fps: kind === "sweep" ? 2 : null, status: "complete",
      elapsedMs: 0, aiLikelihood: 86, classification: "likely_ai_generated",
      summary: "Illustrative inspection: changing truck lettering and merging anatomy.",
      inputTokens: 0, outputTokens: 0, intervals: [{ startSeconds: 0, endSeconds: 15 }],
    })),
  },
  finalScore: 86,
  geminiScore: 86,
  classification: "likely_ai_generated",
  summary:
    "The clip contains several temporal and physical inconsistencies that are difficult to explain as compression or conventional editing.",
  suspiciousMoments: [
    {
      timestamp: "00:04.2",
      observation: "The lettering on the truck changes shape and spelling as the camera moves.",
      severity: "high",
      category: "text",
    },
    {
      timestamp: "00:07.8",
      observation: "The dog’s front paw briefly merges with the steering wheel, then reappears on the dashboard.",
      severity: "high",
      category: "anatomy",
    },
    {
      timestamp: "00:11.1",
      observation: "A shopping cart gains a fifth wheel and its reflection moves in the opposite direction.",
      severity: "medium",
      category: "physics",
    },
  ],
  evidenceAgainstAi: [
    "The lighting direction remains broadly consistent across the clip.",
    "Audio perspective mostly follows the camera position.",
  ],
  alternativeExplanations: [
    "Heavy recompression could explain some edge shimmer.",
    "The clip may combine practical footage with conventional VFX.",
  ],
  provenance: {
    status: "not_found",
    label: "No Content Credentials found",
    detail: "Missing credentials do not prove the video is real.",
  },
  comments: {
    status: "available",
    sampleSize: 78,
    aiClaims: 49,
    realClaims: 6,
    creatorAdmissionFound: false,
    summary: "Most AI claims point to the changing truck text and the dog’s paws.",
  },
  metadata: {
    status: "complete",
    disclosures: [],
  },
  adjustments: [
    {
      source: "gemini",
      delta: 0,
      reason: "The model evidence value is an uncalibrated diagnostic.",
    },
    {
      source: "public_comments",
      delta: 0,
      reason: "Audience opinions are context only and do not change the evidence score.",
    },
  ],
  model: "gemini-3.7-flash",
  processingMode: "agentic",
  agenticProcessingUsed: true,
  analyzedAt: new Date().toISOString(),
  analyzerVersion: "sample-2",
  limitations: [
    "This is a fictional example, not an actual scan or proof of authorship.",
    "Conventional VFX, compression, and edits can resemble AI artifacts.",
  ],
};
