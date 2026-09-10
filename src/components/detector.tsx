"use client";

import { ChangeEvent, FormEvent, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { apiResponseSchema } from "@/lib/analyzer/result-schema";
import { MAX_VIDEO_BYTES, MAX_VIDEO_SECONDS } from "@/lib/media-limits";
import { AnalysisResult, ResultReport } from "./result-report";
import { detectorInputReducer, initialDetectorInput, inputForScan } from "./detector-state";

type ViewState = "idle" | "processing" | "result" | "error";
type ServiceState = "checking" | "ready" | "limited" | "unavailable";
type ApiErrorState = { code: string; message: string; retryable: boolean; retryAfter?: number };
type ServiceProviders = {
  sightengine: boolean;
  gemini: boolean;
  youtube: boolean;
  cache: boolean;
  c2pa: boolean;
};

const MAX_UPLOAD_BYTES = MAX_VIDEO_BYTES;
const MAX_UPLOAD_MB = MAX_UPLOAD_BYTES / 1_000_000;

export function normalizeApiResult(payload: Record<string, unknown>): AnalysisResult {
  const parsed = apiResponseSchema.safeParse(payload);
  if (!parsed.success) throw new Error("The scanner returned an unexpected report format. Please try again.");
  const source = parsed.data.analysis;
  const video = source.videoAnalysis;
  const origin = source.source;
  const youtube = source.youtube;
  const metadata = youtube?.metadata;
  const comments = youtube?.comments;
  const provenance = source.provenance;
  const provenanceFound = provenance.indicatesGenerativeAi;
  const provenanceStatus = provenance.status;
  const provenanceLabel = provenanceFound
    ? provenance.valid && provenance.trusted
      ? "Verified generative Content Credential"
      : "Generative Content Credential assertion found"
    : provenanceStatus === "not_found"
      ? "No Content Credentials found"
      : provenanceStatus === "invalid"
        ? "Invalid Content Credentials"
        : "Provenance could not be verified";

  return {
    id: source.id,
    source: source.cacheHit ? "cache" : "fresh",
    cacheHit: source.cacheHit,
    platform: origin.platform,
    sourceUrl: origin.canonicalUrl,
    title: metadata?.title ?? null,
    thumbnailUrl: metadata?.thumbnailUrl ?? null,
    verdict: source.verdict,
    confidence: source.confidence,
    evidenceLabel: source.evidenceLabel,
    assessmentStatus: source.assessmentStatus,
    reviewRequired: source.reviewRequired,
    decisionReasons: source.decisionReasons,
    visualAssessment: video.visualAssessment,
    audioAssessment: video.audioAssessment,
    identityManipulation: video.identityManipulation,
    inspection: video.inspection,
    specialistEvidence: source.specialistEvidence,
    mediaReceipt: source.mediaReceipt,
    socialContext: source.socialContext,
    detectorFingerprint: source.detectorFingerprint,
    rawReport: source,
    finalScore: source.finalScore,
    geminiScore: source.baseScore,
    classification: video.visualClassification,
    summary: video.summary,
    suspiciousMoments: video.suspiciousMoments,
    evidenceAgainstAi: video.evidenceAgainstAi,
    alternativeExplanations: video.alternativeExplanations,
    provenance: {
      status: provenanceStatus,
      label: provenanceLabel,
      detail: provenance.note,
      indicatesGenerativeAi: provenanceFound,
      valid: provenance.valid,
      trusted: provenance.trusted,
    },
    comments: {
      status: comments?.status === "complete" ? "available" : comments?.status ?? "unavailable",
      sampleSize: comments?.sampleSize ?? 0,
      aiClaims: comments?.commentsClaimingAi ?? 0,
      realClaims: comments?.commentsClaimingReal ?? 0,
      creatorAdmissionFound: comments?.creatorAdmissionFound ?? false,
      summary: comments?.commentSummary ?? "",
      reason: comments?.reason ?? youtube?.reason,
    },
    metadata: {
      status: source.socialContext ? "complete" : youtube?.status ?? "unavailable",
      disclosures: [...(metadata?.disclosureReasons ?? []), ...(source.socialContext?.disclosureReasons ?? [])],
    },
    adjustments: source.adjustments,
    model: source.model,
    processingMode: source.videoProcessing,
    agenticProcessingUsed: video.agenticProcessingObserved,
    analyzedAt: source.analyzedAt,
    analyzerVersion: source.analyzerVersion,
    limitations: source.limitations,
  };
}

export function Detector() {
  const [inputState, updateInput] = useReducer(detectorInputReducer<AnalysisResult>, initialDetectorInput<AnalysisResult>());
  const { mode, url, file, completed } = inputState;
  const result = completed?.report ?? null;
  const isDemo = completed?.isDemo ?? false;
  const [view, setView] = useState<ViewState>("idle");
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const previewRef = useRef<string | null>(null);
  const [error, setError] = useState<ApiErrorState | null>(null);
  const [serviceState, setServiceState] = useState<ServiceState>("checking");
  const [serviceProviders, setServiceProviders] = useState<ServiceProviders | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const reportWrap = useRef<HTMLDivElement>(null);
  const activeRequest = useRef<AbortController | null>(null);
  const [progressPercent, setProgressPercent] = useState(15);
  const [progressStep, setProgressStep] = useState(0);

  const PROGRESS_PHASES = [
    "Ingesting stream & validating media transport…",
    "Decoding video & executing high-FPS temporal sweep…",
    "Inspecting fluid dynamics, physics & diffusion artifacts…",
    "Corroborating cross-pass evidence & synthesizing report…",
  ];

  useEffect(() => {
    if (view !== "processing") {
      setProgressPercent(15);
      setProgressStep(0);
      return;
    }
    const interval = setInterval(() => {
      setProgressPercent((prev) => {
        if (prev >= 92) return 92;
        const next = prev + Math.floor(Math.random() * 4 + 2);
        const step = next > 75 ? 3 : next > 50 ? 2 : next > 25 ? 1 : 0;
        setProgressStep(step);
        return next;
      });
    }, 1200);
    return () => clearInterval(interval);
  }, [view]);

  const hasInput = mode === "url" ? url.trim().length > 8 : Boolean(file);
  const serviceAvailable = serviceState === "ready" || serviceState === "limited";
  const isReady = hasInput && serviceAvailable;
  const unavailableChannels = useMemo(() => {
    if (!serviceProviders?.gemini) return [];
    return [
      !serviceProviders.sightengine ? "specialist visual scan" : null,
      !serviceProviders.youtube ? "YouTube metadata and comments" : null,
      !serviceProviders.cache ? "result cache" : null,
      !serviceProviders.c2pa ? "Content Credentials for uploaded clips" : null,
    ].filter((channel): channel is string => Boolean(channel));
  }, [serviceProviders]);
  const platformHint = useMemo(() => {
    const value = url.toLowerCase();
    if (value.includes("youtu")) return "YouTube detected";
    if (value.includes("tiktok")) return "TikTok detected";
    if (value.includes("instagram")) return "Instagram detected";
    if (/(?:^|[./])(?:x|twitter)\.com(?:[/:]|$)/.test(value)) {
      return /\/(?:[^/?#]+\/status|i\/web\/status|statuses)\/\d+(?:[/?#]|$)/.test(value)
        ? "X status link detected"
        : "X link · use a status URL";
    }
    return "YouTube · TikTok · Instagram · X";
  }, [url]);



  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/health", { signal: controller.signal, cache: "no-store" })
      .then(async (response) => {
        const payload = (await response.json()) as {
          providers?: Partial<ServiceProviders>;
        };
        const providers: ServiceProviders = {
          sightengine: Boolean(payload.providers?.sightengine),
          gemini: Boolean(payload.providers?.gemini),
          youtube: Boolean(payload.providers?.youtube),
          cache: Boolean(payload.providers?.cache),
          c2pa: Boolean(payload.providers?.c2pa),
        };
        setServiceProviders(providers);
        setServiceState(
          !providers.gemini
            ? "unavailable"
            : providers.youtube && providers.cache && providers.c2pa
              ? "ready"
              : "limited",
        );
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setServiceProviders(null);
          setServiceState("unavailable");
        }
      });
    return () => controller.abort();
  }, []);

  useEffect(() => () => {
    activeRequest.current?.abort();
    if (previewRef.current) URL.revokeObjectURL(previewRef.current);
  }, []);

  function revealReport() {
    window.setTimeout(() => {
      reportWrap.current?.focus({ preventScroll: true });
      reportWrap.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 80);
  }

  async function runAnalysis(event?: FormEvent, fresh = false) {
    event?.preventDefault();
    const input = inputForScan(inputState, fresh);
    if (!input || !serviceAvailable || activeRequest.current) return;

    setError(null);
    updateInput({ type: "clear-report" });
    setView("processing");
    const controller = new AbortController();
    activeRequest.current = controller;

    try {
      const request = input.mode === "url"
        ? fetch("/api/analyze", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url: input.url, fresh }),
            signal: controller.signal,
          })
        : (() => {
            const form = new FormData();
            form.append("file", input.file);
            form.append("fresh", String(fresh));
            return fetch("/api/analyze/upload", { method: "POST", body: form, signal: controller.signal });
          })();

      const response = await request;
      const payload = (await response.json()) as Record<string, unknown>;
      if (!response.ok) {
        const apiError = typeof payload.error === "object" && payload.error
          ? (payload.error as Record<string, unknown>).message
          : payload.error;
        const details = typeof payload.error === "object" && payload.error
          ? payload.error as Record<string, unknown>
          : {};
        setError({
          code: String(details.code ?? "ANALYSIS_FAILED"),
          message: String(apiError ?? payload.message ?? "The scan could not be completed."),
          retryable: Boolean(details.retryable ?? true),
          retryAfter: typeof details.retryAfter === "number" ? details.retryAfter : undefined,
        });
        setView("error");
        return;
      }

      updateInput({ type: "completed", report: normalizeApiResult(payload), input });
      setView("result");
      revealReport();
    } catch (reason) {
      if (controller.signal.aborted) return;
      setError({
        code: "INVALID_RESPONSE",
        message: reason instanceof Error ? reason.message : "The scan could not be completed.",
        retryable: true,
      });
      setView("error");
    } finally {
      if (activeRequest.current === controller) activeRequest.current = null;
    }
  }

  function handleFile(event: ChangeEvent<HTMLInputElement>) {
    const selected = event.target.files?.[0] ?? null;
    if (previewRef.current) URL.revokeObjectURL(previewRef.current);
    previewRef.current = null;
    setPreviewUrl(null);
    if (selected && selected.size > MAX_UPLOAD_BYTES) {
      event.target.value = "";
      updateInput({ type: "file", file: null });
      setError({
        code: "FILE_TOO_LARGE",
        message: `Choose a video smaller than ${MAX_UPLOAD_MB} MB.`,
        retryable: false,
      });
      setView("error");
      return;
    }
    updateInput({ type: "file", file: selected });
    if (selected) {
      const objectUrl = URL.createObjectURL(selected);
      previewRef.current = objectUrl;
      setPreviewUrl(objectUrl);
    }
    setError(null);
    if (view === "error") setView("idle");
  }

  return (
    <main className="app-shell" id="top">
      <header className="site-header">
        <div className="brand-wrapper">
          <img
            src="/logo.png"
            alt="AI Slop Detector Emblem"
            className="brand-logo-img"
            width="44"
            height="44"
          />
          <div className="brand-text-col">
            <a className="brand" href="#top">
              <span className="brand-text__main">AI Slop</span>
              <span className="brand-text__detector">Detector</span>
            </a>
            <span className="brand-tagline">REAL CONTENT. VERIFIED.</span>
          </div>
        </div>
        <span className="brand-badge">Forensics v3</span>
      </header>

      <div className="hero-banner-wrap">
        <img
          src="/banner.png"
          alt="AI Slop Detector - Real Content. Verified."
          className="hero-banner-img"
          width="1200"
          height="400"
        />
      </div>

      <section className="scanner" aria-labelledby="scanner-title">
        <div className="scanner__intro">
          <div className="scanner-badge">
            <span className="scanner-badge__pulse" aria-hidden="true" />
            <span>Agentic Deepfake & AI Video Intelligence</span>
          </div>
          <h1 id="scanner-title">Verify video authenticity.</h1>
          <p>Unmask generative diffusion models and concept deepfakes across YouTube, TikTok, Instagram, and X with multi-pass forensic verification.</p>
        </div>

        <form className="scanner__form" onSubmit={(event) => void runAnalysis(event)} aria-busy={view === "processing"}>
          <div className="scanner__tabs" role="group" aria-label="Choose video input type">
            <button type="button" aria-pressed={mode === "url"} disabled={view === "processing"} onClick={() => updateInput({ type: "mode", mode: "url" })}>Paste link</button>
            <button type="button" aria-pressed={mode === "upload"} disabled={view === "processing"} onClick={() => updateInput({ type: "mode", mode: "upload" })}>Upload video</button>
          </div>

          <div className={`scanner__input-row ${mode === "upload" ? "scanner__input-row--upload" : ""}`}>
            {mode === "url" ? (
              <label className="url-field">
                <span className="sr-only">Video URL</span>
                <svg className="url-field__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
                  <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
                </svg>
                <input
                  suppressHydrationWarning
                  disabled={view === "processing"}
                  type="text"
                  inputMode="url"
                  autoCapitalize="none"
                  autoCorrect="off"
                  spellCheck={false}
                  placeholder="Paste a YouTube, TikTok, Instagram, or X link…"
                  value={url}
                  aria-describedby="input-hint"
                  onChange={(event) => {
                    updateInput({ type: "url", url: event.target.value });
                    setError(null);
                    if (view === "error") setView("idle");
                  }}
                />
              </label>
            ) : (
              <div className="file-field">
                <input ref={fileInput} suppressHydrationWarning type="file" accept="video/mp4,video/quicktime,video/webm,video/x-msvideo" onChange={handleFile} hidden />
                <button className="file-picker" type="button" disabled={view === "processing"} onClick={() => fileInput.current?.click()}>
                  <span className="file-picker__name">{file ? file.name : "Choose a video file to inspect"}</span>
                  <span className="file-picker__meta">{file ? `${(file.size / 1_000_000).toFixed(1)} MB · Click to change file` : "MP4, MOV, WebM or AVI"}</span>
                </button>
              </div>
            )}
            <button className="scan-button" type="submit" disabled={!isReady || view === "processing"}>
              {view === "processing" ? (
                <>
                  <span className="processing__spinner" style={{ width: 16, height: 16, marginTop: 0 }} aria-hidden="true" />
                  <span>Scanning…</span>
                </>
              ) : (
                <>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <circle cx="11" cy="11" r="8" />
                    <line x1="21" y1="21" x2="16.65" y2="16.65" />
                  </svg>
                  <span>Scan video</span>
                </>
              )}
            </button>
          </div>

          <div className="input-hint" id="input-hint">
            <span className="platform-pill">{mode === "url" ? platformHint : `Up to ${MAX_UPLOAD_MB} MB`}</span>
            <span>Up to {MAX_VIDEO_SECONDS / 60} minutes</span>
          </div>

          {mode === "upload" && previewUrl && <details className="upload-preview">
            <summary>Preview selected video</summary>
            <video controls preload="metadata" src={previewUrl} aria-label="Preview of your selected upload" />
          </details>}

          {serviceState === "unavailable" && <p className="setup-notice" role="status">The scanner is unavailable. Check the server connection and API configuration.</p>}
          {serviceState === "checking" && <p className="service-check" role="status">Connecting to the scanner…</p>}
          {serviceAvailable && serviceProviders && !serviceProviders.sightengine && <p className="setup-notice" role="status">Sightengine is unavailable. This scan will use AI Tech only.</p>}

          {view === "processing" && (
            <>
              <div className="forensic-progress" role="status" aria-label="Analysis progress">
                <div className="forensic-progress__header">
                  <div className="forensic-progress__phase">
                    <span className="forensic-progress__radar" aria-hidden="true" />
                    <span>{PROGRESS_PHASES[progressStep]}</span>
                  </div>
                  <span className="forensic-progress__percent">{progressPercent}%</span>
                </div>
                <div className="forensic-progress__track" aria-hidden="true">
                  <div className="forensic-progress__bar" style={{ width: `${progressPercent}%` }} />
                </div>
                <div className="forensic-progress__steps" aria-hidden="true">
                  <span className={progressStep >= 0 ? "forensic-progress__step--active" : ""}>1. Transport</span>
                  <span className={progressStep >= 1 ? "forensic-progress__step--active" : ""}>2. Temporal</span>
                  <span className={progressStep >= 2 ? "forensic-progress__step--active" : ""}>3. Artifacts</span>
                  <span className={progressStep >= 3 ? "forensic-progress__step--active" : ""}>4. Synthesis</span>
                </div>
              </div>

              <div className="processing sr-only" role="status">
                <span className="processing__spinner" aria-hidden="true" />
                <div><strong>Analyzing your video</strong><p>This can take a few minutes. Your result will appear here.</p></div>
              </div>
            </>
          )}

          {view === "error" && <div className="error-card" role="alert">
            <strong>{error?.code === "UNSUPPORTED_VIDEO_URL" ? "That link isn’t a supported video post."
              : error?.code === "MEDIA_RETRIEVAL_FAILED" ? "We couldn’t retrieve that video." : "We couldn’t inspect that clip."}</strong>
            <p>{error?.message}</p>
            {error?.retryAfter && <p>Try again in about {error.retryAfter} seconds.</p>}
            {mode === "url" && error?.code === "MEDIA_RETRIEVAL_FAILED" && <button type="button" onClick={() => updateInput({ type: "mode", mode: "upload" })}>Upload the video instead</button>}
          </div>}
        </form>

        <aside className="accuracy-note" aria-label="Important limitation">
          Experimental. Results can miss AI or flag real footage. A scan cannot verify a video’s origin.
        </aside>
      </section>

      {view === "result" && result && <div id="report" className="report-wrap" ref={reportWrap} tabIndex={-1}>
        <ResultReport result={result} isDemo={isDemo} onRescan={serviceAvailable && completed?.input ? () => void runAnalysis(undefined, true) : undefined} />
      </div>}

      <footer className="site-footer">
        <details className="scan-info">
          <summary>How it works & privacy</summary>
          <div className="detail-body">
            <p>Sightengine is the primary visual detector. Gemini provides a separate review, alongside available Content Credentials and creator disclosures.</p>
            <p>Videos are sent to Google Gemini and, when configured, Sightengine. We request deletion of Gemini uploads after analysis; Google may retain them for up to 48 hours if cleanup fails. Sightengine processing follows its own data policy.</p>
            <p>{serviceProviders?.cache ? "Completed reports and file hashes may be cached. A fresh scan bypasses the saved result."
              : serviceState === "checking" ? "Checking result cache availability."
                : serviceProviders ? "Result caching is unavailable. Repeated scans may be analyzed again." : "Result cache availability could not be confirmed."}</p>
            {unavailableChannels.length > 0 && <p>Optional services unavailable: {unavailableChannels.join(", ")}.</p>}
          </div>
        </details>
      </footer>
    </main>
  );
}
