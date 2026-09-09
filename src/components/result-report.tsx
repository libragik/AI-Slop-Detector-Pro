"use client";

import { useState } from "react";
import { SpecialistEvidence } from "./specialist-evidence";
import type { SightengineEvidence } from "@/lib/analyzer/sightengine-types";
import type { ScoreResult, VideoAnalysis, VideoInspection } from "@/lib/analyzer/types";
import type { MediaReceipt, SocialMediaContext } from "@/lib/analyzer/media-context";

export type AnalysisResult = {
  specialistEvidence?: SightengineEvidence | null;
  id?: string;
  source?: string;
  cacheHit?: boolean;
  platform?: string;
  sourceUrl?: string | null;
  title?: string | null;
  thumbnailUrl?: string | null;
  verdict: ScoreResult["verdict"];
  confidence: ScoreResult["confidence"];
  evidenceLabel?: string;
  assessmentStatus: ScoreResult["assessmentStatus"];
  reviewRequired: boolean;
  decisionReasons: string[];
  finalScore: number;
  geminiScore?: number;
  classification?: string;
  summary: string;
  suspiciousMoments: VideoAnalysis["suspiciousMoments"];
  evidenceAgainstAi: string[];
  alternativeExplanations: string[];
  visualAssessment: VideoAnalysis["visualAssessment"];
  audioAssessment: VideoAnalysis["audioAssessment"];
  identityManipulation: VideoAnalysis["identityManipulation"];
  inspection?: VideoInspection;
  mediaReceipt?: MediaReceipt | null;
  socialContext?: SocialMediaContext | null;
  detectorFingerprint?: string;
  rawReport?: object;
  provenance?: {
    status?: string;
    label?: string;
    detail?: string;
    indicatesGenerativeAi?: boolean;
    valid?: boolean | null;
    trusted?: boolean | null;
  };
  comments?: {
    status?: string;
    sampleSize?: number;
    aiClaims?: number;
    realClaims?: number;
    creatorAdmissionFound?: boolean;
    summary?: string;
    reason?: string;
  };
  model?: string;
  processingMode?: string;
  agenticProcessingUsed?: boolean;
  analyzedAt?: string;
  analyzerVersion?: string;
  metadata?: { status?: string; disclosures?: string[] };
  adjustments?: Array<{ source: string; delta: number; reason: string }>;
  limitations?: string[];
};

function momentUrl(sourceUrl: string | null | undefined, timestamp: string): string | null {
  if (!sourceUrl) return null;
  try {
    const target = new URL(sourceUrl);
    if (!/(^|\.)youtube\.com$/.test(target.hostname) && target.hostname !== "youtu.be") return null;
    if (!/^(?:\d{1,2}:)?\d{1,3}:\d{2}(?:\.\d{1,3})?$/.test(timestamp)) return null;
    const parts = timestamp.split(":").map(Number);
    if (parts.at(-1)! >= 60 || (parts.length === 3 && parts[1] >= 60)) return null;
    const seconds = parts.reduce((total, part) => total * 60 + part, 0);
    target.searchParams.set("t", `${Math.floor(seconds)}s`);
    return target.toString();
  } catch {
    return null;
  }
}

const assessmentLabels = {
  generated: "Generation indicators",
  edited: "AI editing indicators",
  likely_authentic: "No clear visual indicators",
  inconclusive: "Uncertain",
  synthetic: "Possible AI audio · unverified",
  likely_synthetic: "Possible AI audio · unverified",
  likely_recorded: "No clear audio indicators",
  face_swap: "Face replacement indicators",
  lip_sync_manipulation: "Lip-sync manipulation indicators",
  none_detected: "No clear identity changes",
};

function durationLabel(seconds: number) {
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

function intervalTimestamp(seconds: number) {
  const milliseconds = Math.round(seconds * 1_000);
  const whole = Math.floor(milliseconds / 1_000);
  const fraction = String(milliseconds % 1_000).padStart(3, "0").replace(/0+$/, "");
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}${fraction ? `.${fraction}` : ""}`;
}

type Annotation = { rating: string; note: string; savedAt?: string };

function ReportActions({ result, isDemo, onRescan }: { result: AnalysisResult; isDemo: boolean; onRescan?: () => void }) {
  const storageKey = `ai-slop-detector:annotation:${result.id ?? "report"}`;
  const [annotation, setAnnotation] = useState<Annotation>(() => {
    if (typeof window === "undefined" || isDemo) return { rating: "", note: "" };
    try {
      const stored = JSON.parse(localStorage.getItem(storageKey) ?? "null") as Annotation | null;
      return stored && typeof stored.rating === "string" && typeof stored.note === "string"
        ? { rating: stored.rating, note: stored.note, savedAt: stored.savedAt }
        : { rating: "", note: "" };
    } catch { return { rating: "", note: "" }; }
  });
  const [saveStatus, setSaveStatus] = useState("");

  function saveAnnotation() {
    try {
      const saved = { ...annotation, savedAt: new Date().toISOString() };
      localStorage.setItem(storageKey, JSON.stringify(saved));
      setAnnotation(saved);
      setSaveStatus("Saved on this browser. Nothing was sent.");
    } catch { setSaveStatus("This browser could not save the note. You can still include it in a downloaded report."); }
  }

  function downloadReport() {
    const blob = new Blob([JSON.stringify({
      format: "ai-slop-detector-report/v2",
      sample: isDemo,
      report: result.rawReport ?? result,
      annotation: annotation.rating || annotation.note ? { ...annotation, status: "user annotation; not verified ground truth" } : null,
    }, null, 2)], { type: "application/json" });
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = `ai-evidence-${(result.id ?? "report").replace(/[^a-zA-Z0-9_-]/g, "").slice(0, 64)}.json`;
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1_000);
  }

  return (
    <div className="report-actions">
      <div className="report-actions__buttons">
        <button type="button" onClick={downloadReport}>Download report</button>
        {!isDemo && onRescan && <button type="button" onClick={onRescan} aria-label="Fresh scan of this report’s video">Rescan video</button>}
      </div>
      <details className="report-note report-details">
        <summary>Add a private note</summary>
        <div className="detail-body">
        <p>Your note stays in this browser and is included when you download this report. It does not change the assessment or train the detector.</p>
        <label>
          Your assessment
          <select value={annotation.rating} onChange={(event) => { setAnnotation({ ...annotation, rating: event.target.value }); setSaveStatus(""); }}>
            <option value="">Choose a note type</option>
            <option value="missed_ai">The detector may have missed AI</option>
            <option value="false_alarm">The detector may have raised a false alarm</option>
            <option value="needs_investigation">This needs more investigation</option>
            <option value="useful">This report was useful</option>
          </select>
        </label>
        <label>
          What did you notice?
          <textarea maxLength={2000} rows={3} value={annotation.note} placeholder="Add a timestamp, source, or observation…" onChange={(event) => { setAnnotation({ ...annotation, note: event.target.value }); setSaveStatus(""); }} />
        </label>
        <button type="button" onClick={saveAnnotation} disabled={!annotation.rating && !annotation.note}>Save note on this browser</button>
        <p role="status">{saveStatus || (annotation.savedAt ? "A note is saved on this browser." : "Notes are private and are never submitted to a server.")}</p>
        </div>
      </details>
    </div>
  );
}

export function ResultReport({ result, isDemo = false, onRescan }: { result: AnalysisResult; isDemo?: boolean; onRescan?: () => void }) {
  const provenanceVerified = result.provenance?.status === "found" && result.provenance.indicatesGenerativeAi && result.provenance.valid && result.provenance.trusted;
  const inspection = result.inspection;
  const disclosureReasons = [...new Set([...(result.metadata?.disclosures ?? []), ...(result.socialContext?.disclosureReasons ?? [])])];
  const hasSocialContext = Boolean(result.socialContext?.caption || disclosureReasons.length);
  const completedPasses = inspection?.passes.filter((pass) => pass.status === "complete").length ?? 0;
  const completedSweep = inspection?.passes.some((pass) => pass.kind === "sweep" && pass.status === "complete");
  const completedReview = inspection?.passes.some((pass) => pass.kind === "review" && pass.status === "complete");
  const completedFollowUp = inspection?.passes.some((pass) => pass.kind === "adjudication" && pass.status === "complete");
  const reviewLabel = !inspection || inspection.reviewAgreement === "not_available" ? "Review incomplete"
    : inspection.reviewAgreement === "disagree" ? "Reviews disagree"
      : inspection.reviewAgreement === "resolved" && completedFollowUp && completedPasses >= 2 ? "Difference resolved by follow-up"
        : inspection.reviewAgreement === "agree" && completedSweep && completedReview ? "Separate reviews agree"
          : "Review incomplete";
  const coverageDescription = !inspection || !completedPasses
    ? "No completed inspection is available to establish coverage."
    : completedSweep && completedReview && inspection.temporalCoverage === "adequate"
      ? "The requested timeline sweep and a separate review completed. This does not verify that every frame was inspected."
      : completedSweep && inspection.temporalCoverage === "adequate"
        ? "The requested timeline sweep completed, but a separate review did not. Inspection remains limited."
        : "Some analysis completed, but sufficient timeline coverage is not established. See the pass details for inspection limits.";

  return (
    <section className="report" aria-label="Video analysis result">
      <div className="report__header">
        <div className="report__meta">
          <span>{isDemo ? "Illustrative sample · not an actual scan" : result.cacheHit ? "Saved result" : "Result"}</span>
          <span>
            {result.sourceUrl ? <a href={result.sourceUrl} target="_blank" rel="noreferrer">{result.title ?? `${result.platform === "x" ? "X" : (result.platform ?? "Video").replace(/^./, (letter) => letter.toUpperCase())} video`}</a>
              : result.platform === "upload" ? "Uploaded video" : "Video"}
            {result.mediaReceipt ? ` · ${durationLabel(result.mediaReceipt.durationSeconds)}` : ""}
          </span>
        </div>
        <h2>{result.verdict}</h2>
        <p className="report__dek">{result.decisionReasons[0]}</p>
        <p className="evidence-label">{provenanceVerified ? "AI credential verified"
          : result.verdict === "AI indicators detected" && result.specialistEvidence?.verdict === "persistent_ai_indicators"
            ? "Primary detector: Sightengine · Origin unverified"
            : result.assessmentStatus === "conflicting" ? "Conflicting evidence · review required"
              : result.reviewRequired ? "Limited assessment · review required"
                : "Origin unverified"}</p>
      </div>

      <div className="report__details">
        {result.specialistEvidence && <SpecialistEvidence evidence={result.specialistEvidence} />}

        <details className="report-details">
          <summary><span>Gemini review</span><span className="detail-summary">{assessmentLabels[result.visualAssessment]}</span></summary>
          <div className="detail-body">
            <p className="detail-intro">Gemini’s interpretation is a separate review and can be wrong.</p>
            <dl className="findings-list" aria-label="Model findings by media type">
              <div><dt>Gemini visual review</dt><dd>{assessmentLabels[result.visualAssessment]}</dd></div>
              <div><dt>Voice & audio</dt><dd>{inspection?.audioCoverage === "no_audio" ? "No audio track" : assessmentLabels[result.audioAssessment]}</dd></div>
              <div><dt>Identity changes</dt><dd>{assessmentLabels[result.identityManipulation]}</dd></div>
            </dl>
            <p>{result.summary}</p>
            {result.suspiciousMoments.length > 0 && <>
              <h3>Observations to inspect</h3>
              <ol className="moment-list">{result.suspiciousMoments.map((moment, index) => <li key={`${moment.timestamp}-${index}`}>
                <div className="moment-list__topline">
                  {momentUrl(result.sourceUrl, moment.timestamp) ? <a href={momentUrl(result.sourceUrl, moment.timestamp)!} target="_blank" rel="noreferrer" title="Open this moment on YouTube"><time>{moment.timestamp}</time></a> : <time>{moment.timestamp}</time>}
                  <span>{moment.severity} severity</span>
                </div>
                <p>{moment.observation}</p>
              </li>)}</ol>
            </>}
            {result.evidenceAgainstAi.length > 0 && <><h3>Counterevidence</h3><ul>{result.evidenceAgainstAi.map((item) => <li key={item}>{item}</li>)}</ul></>}
            {result.alternativeExplanations.length > 0 && <><h3>Other possible explanations</h3><ul>{result.alternativeExplanations.map((item) => <li key={item}>{item}</li>)}</ul></>}
            <h3>{inspection ? `${completedPasses} completed analysis ${completedPasses === 1 ? "pass" : "passes"}` : "Inspection coverage unavailable"}</h3>
            <p>{coverageDescription}</p>
            <p>{reviewLabel}</p>
            <dl className="findings-list">
              <div><dt>Visual coverage</dt><dd>{inspection?.visualCoverage ?? "unknown"}</dd></div>
              <div><dt>Timeline coverage</dt><dd>{inspection?.temporalCoverage ?? "unknown"}</dd></div>
              <div><dt>Audio coverage</dt><dd>{inspection?.audioCoverage === "no_audio" ? "no track" : inspection?.audioCoverage ?? "unknown"}</dd></div>
            </dl>
          </div>
        </details>

        <details className="report-details">
          <summary>Source & credentials</summary>
          <div className="detail-body">
            <h3>{result.platform === "upload" ? "Your uploaded file" : "Media from this post"}</h3>
            {result.mediaReceipt ? <p>{durationLabel(result.mediaReceipt.durationSeconds)} · {result.mediaReceipt.width} × {result.mediaReceipt.height} · {result.mediaReceipt.hasAudio ? "Audio track present" : "No audio track"}</p>
              : <p>The public video link was provided directly to the model. An exact downloaded-file fingerprint is unavailable for this report.</p>}
            {result.sourceUrl && <a href={result.sourceUrl} target="_blank" rel="noreferrer">Open original post</a>}
            <h3>{result.provenance?.label ?? "No verified provenance"}</h3>
            <p className="credential-status">{provenanceVerified ? "VERIFIED AI ASSERTION" : result.provenance?.indicatesGenerativeAi ? "UNVERIFIED AI ASSERTION" : "ORIGIN NOT VERIFIED"}</p>
            <p>{result.provenance?.detail ?? "Missing Content Credentials are neutral evidence."}</p>
            <h3>{disclosureReasons.length ? "AI use disclosed" : hasSocialContext || result.metadata?.status === "complete" ? "No explicit AI disclosure found" : "Creator context unavailable"}</h3>
            {disclosureReasons.length ? <ul>{disclosureReasons.map((reason) => <li key={reason}>{reason}</li>)}</ul> : <p>A missing disclosure does not establish how this video was made.</p>}
            {result.socialContext?.caption && <details className="nested-details"><summary>Post caption</summary><blockquote>{result.socialContext.caption}</blockquote></details>}
          </div>
        </details>

        <details className="report-details">
          <summary>Assessment details</summary>
          <div className="detail-body">
            <h3>Why this result</h3>
            <ul>{result.decisionReasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
            <h3>Limitations</h3>
            <ul>{(result.limitations?.length ? result.limitations : ["This is an evidence assessment, not proof of authorship."]).map((item) => <li key={item}>{item}</li>)}</ul>

            <details className="nested-details inspection-details">
              <summary>Technical details & source receipt</summary>
              <p>Model evidence values are diagnostic scores, not percentages, probabilities, or calibrated confidence. Audience comments never adjust them.</p>
              <dl className="receipt-list">
                <div><dt>Model</dt><dd>{result.model ?? "Unavailable"}</dd></div>
                <div><dt>Detector version</dt><dd>{result.analyzerVersion ?? "Unavailable"}</dd></div>
                <div><dt>Detector fingerprint</dt><dd>{result.detectorFingerprint ?? "Sample only"}</dd></div>
                <div><dt>Model evidence value</dt><dd>{result.inspection && !result.inspection.passes.some(pass => pass.status === "complete")
                  ? "Unavailable" : `${result.geminiScore ?? result.finalScore} / 99 · uncalibrated`}</dd></div>
                {result.mediaReceipt && <>
                  <div><dt>File SHA-256</dt><dd>{result.mediaReceipt.sha256}</dd></div>
                  <div><dt>File details</dt><dd>{result.mediaReceipt.mimeType} · {(result.mediaReceipt.sizeBytes / 1_000_000).toFixed(2)} MB · {result.mediaReceipt.fps ?? "Unknown"} fps</dd></div>
                  <div><dt>Source media ID</dt><dd>{result.mediaReceipt.mediaId ?? "Local upload"}</dd></div>
                </>}
              </dl>
              {inspection?.passes.map((pass, index) => <article className="inspection-pass" key={`${pass.kind}-${index}`}>
                <h4>{index + 1}. {pass.kind === "sweep" ? "Timeline sweep" : pass.kind === "review" ? "Separate review" : "Targeted follow-up"} · {pass.status === "complete" ? "completed" : "failed"}</h4>
                <p>{pass.summary}</p>
                {pass.validForCorroboration === false && <p>This pass did not provide consistent, sufficient evidence to support a settled conclusion.</p>}
                {pass.consistencyIssues?.length ? <ul>{pass.consistencyIssues.map((issue) => <li key={issue}>{issue}</li>)}</ul> : null}
                <small>{pass.model} · {pass.mode}{pass.fps ? ` · ${pass.fps} fps full timeline requested` : ""} · {(pass.elapsedMs / 1000).toFixed(1)}s</small>
                {pass.intervals.length > 0 && <p>Requested intervals: {pass.intervals.map((interval) => `${intervalTimestamp(interval.startSeconds)}–${intervalTimestamp(interval.endSeconds)}${interval.fps === undefined ? "" : interval.fps === null ? " at agentic sampling" : ` at ${interval.fps} fps`}`).join(", ")}</p>}
              </article>)}
              {inspection?.issues.length ? <ul>{inspection.issues.map((issue) => <li key={issue}>{issue}</li>)}</ul> : null}
              <h4>Audience context</h4>
              {result.comments?.status === "available" ? <p>{result.comments.aiClaims ?? 0} AI claims and {result.comments.realClaims ?? 0} real claims in {result.comments.sampleSize ?? 0} sampled comments. {result.comments.summary} These opinions do not determine the verdict.</p> : <p>{result.comments?.reason ?? "No audience comments were included."}</p>}
            </details>
          </div>
        </details>
      </div>

      <ReportActions key={`${result.id}-${isDemo}`} result={result} isDemo={isDemo} onRescan={onRescan} />
      <p className="report__timestamp">{isDemo ? "Fictional example for illustration" : result.analyzedAt ? `Analyzed ${new Date(result.analyzedAt).toLocaleString()}` : "Analysis time unavailable"}</p>
    </section>
  );
}
