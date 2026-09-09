import { createHash } from "node:crypto";
import { createReadStream, openAsBlob } from "node:fs";
import { lstat } from "node:fs/promises";
import { setTimeout as delay } from "node:timers/promises";
import pLimit from "p-limit";

import { env } from "@/lib/config/env";
import type { MediaReceipt } from "./media-context";
import type { SightengineEvidence, SightengineFailureCode, SightengineSample } from "./sightengine-types";

// Server-only Node module. These private variables are never NEXT_PUBLIC values.
const API_ROOT = "https://api.sightengine.com/1.0/";
// These select the provider transport; they do not reject larger/longer videos.
const DIRECT_UPLOAD_BYTES = 50_000_000;
const MAX_RESPONSE_BYTES = 1_048_576;
const REQUEST_TIMEOUT_MS = 120_000;
const ASYNC_TIMEOUT_MS = 600_000;
const POLL_INTERVAL_MS = 3_000;
export const SIGHTENGINE_POLICY_FINGERPRINT = "6544a9d76ce994fecfc2c736b4f3af79b744f1cafa11a1e66145e849e30aea89";
export const SIGHTENGINE_POLICY_VERSION = "sightengine-temporal-evidence-v1";
const requestQueue = pLimit(2);

const isNumber = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const object = (value: unknown): Record<string, unknown> | null =>
  value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;

// Compare the reported decimal timestamps without subtraction roundoff around
// the inclusive .6-second boundary. No tolerance silently widens the policy.
function decimalParts(value: number): [bigint, number] {
  const [mantissa, exponent = "0"] = String(value).toLowerCase().split("e");
  const [whole, fraction = ""] = mantissa.split(".");
  return [BigInt(whole + fraction), Number(exponent) - fraction.length];
}

function gapWithin(later: number, earlier: number, maximum: number): boolean {
  if (later <= earlier) return false;
  const values = [later, earlier, maximum].map(decimalParts);
  const exponent = Math.min(...values.map(([, power]) => power));
  const [end, start, limit] = values.map(([integer, power]) => integer * 10n ** BigInt(power - exponent));
  return end - start <= limit;
}

export function isSightengineConfigured(): boolean {
  return typeof window === "undefined" && Boolean(process.env.SIGHTENGINE_API_USER?.trim()
    && process.env.SIGHTENGINE_API_SECRET?.trim());
}

export function aggregateSightengineEvidence(samples: unknown, options: {
  durationSeconds: unknown;
  technicalComplete: boolean;
  declaredIntervalSeconds: unknown;
}): SightengineEvidence {
  const technicalIssues: string[] = [];
  const coverageIssues: string[] = [];
  const duration = isNumber(options.durationSeconds) && options.durationSeconds > 0 ? options.durationSeconds : null;
  if (duration === null) technicalIssues.push("duration_must_be_finite_and_positive");
  if (options.technicalComplete !== true) technicalIssues.push("caller_has_not_confirmed_technical_completion");
  if (options.declaredIntervalSeconds !== 0.5) technicalIssues.push("declared_sampling_interval_is_not_0.5_seconds");
  if (!Array.isArray(samples)) technicalIssues.push("samples_must_be_a_list");
  const records: SightengineSample[] = (Array.isArray(samples) ? samples : []).map((sample: unknown, index) => {
    const entry = object(sample);
    const position = entry?.positionSeconds;
    const score = entry?.aiGenerated;
    const positionValid = isNumber(position) && duration !== null && position >= 0 && position < duration;
    const scoreValid = isNumber(score) && score >= 0 && score <= 1;
    const issues: string[] = [];
    if (!entry) issues.push("sample_must_be_an_object");
    if (!positionValid) issues.push("position_must_be_finite_and_in_video");
    if (!scoreValid) issues.push("score_must_be_finite_and_in_unit_interval");
    if (issues.length) technicalIssues.push(`invalid_sample_at_index_${index}`);
    return {
      index,
      rawPositionMilliseconds: isNumber(entry?.rawPositionMilliseconds) ? entry.rawPositionMilliseconds : null,
      positionSeconds: isNumber(position) ? position : null,
      aiGenerated: isNumber(score) ? score : null,
      valid: positionValid && scoreValid,
      positive: positionValid && scoreValid ? score >= 0.5 : null,
      issues,
    };
  });

  const candidates: SightengineSample[][] = [];
  let current: SightengineSample[] = [];
  for (const record of records) {
    const previous = current.at(-1);
    const canExtend = previous && record.valid && record.positive && previous.index + 1 === record.index
      && gapWithin(record.positionSeconds!, previous.positionSeconds!, 0.6);
    if (current.length && !canExtend) {
      candidates.push(current);
      current = [];
    }
    if (record.valid && record.positive) current.push(record);
  }
  if (current.length) candidates.push(current);

  const persistentRuns: SightengineEvidence["persistentRuns"] = candidates.filter((run) => run.length >= 2).map((run) => ({
    sampleIndices: run.map((sample) => sample.index),
    sampledPositionsSeconds: run.map((sample) => sample.positionSeconds!),
    sampleScores: run.map((sample) => sample.aiGenerated!),
    firstSampleSeconds: run[0].positionSeconds!,
    lastSampleSeconds: run.at(-1)!.positionSeconds!,
    extentMeaning: "sample_endpoints_only_not_a_continuous_AI_interval",
    adjacentSamplesAreIndependent: false,
  }));
  const isolatedAlerts: SightengineEvidence["isolatedAlerts"] = candidates.filter((run) => run.length === 1).map(([sample]) => ({
    sampleIndex: sample.index, positionSeconds: sample.positionSeconds!, aiGenerated: sample.aiGenerated!, status: "unresolved",
  }));
  if (!records.length) coverageIssues.push("no_samples");
  else if (!records.every((sample) => sample.valid)) coverageIssues.push("invalid_samples_prevent_complete_coverage");
  const first = records[0];
  const last = records.at(-1);
  if (first?.valid && first.positionSeconds! > 0.1) coverageIssues.push("initial_coverage_gap");
  if (last?.valid && duration !== null && !gapWithin(duration, last.positionSeconds!, 0.6)) coverageIssues.push("terminal_coverage_gap");
  for (let index = 1; index < records.length; index++) {
    const previous = records[index - 1];
    const record = records[index];
    if (previous.valid && record.valid) {
      if (record.positionSeconds! <= previous.positionSeconds!) coverageIssues.push(`positions_not_strictly_increasing_at_index_${index}`);
      else if (!gapWithin(record.positionSeconds!, previous.positionSeconds!, 0.6)) coverageIssues.push(`coverage_gap_at_index_${index}`);
    }
  }
  const complete = !technicalIssues.length && !coverageIssues.length;
  const verdict = !complete ? "inconclusive" : persistentRuns.length ? "persistent_ai_indicators"
    : isolatedAlerts.length ? "inconclusive" : "no_clear_indicators";
  const reasons = [!complete ? "Technical or sampling coverage requirements were not completed."
    : persistentRuns.length ? "At least two consecutive positive sampled observations meet the fixed spacing rule."
      : isolatedAlerts.length ? "Isolated positive samples remain unresolved."
        : "No positive samples were returned in the completed declared 2 Hz scan."];
  if (isolatedAlerts.length && !reasons.includes("Isolated positive samples remain unresolved.")) reasons.push("Isolated positive samples remain unresolved.");
  reasons.push("Sampled evidence does not establish origin or exclude AI between samples, including subsecond inserts.");
  return {
    schemaVersion: 1, provider: "sightengine", model: "genai",
    policyVersion: SIGHTENGINE_POLICY_VERSION, policyFingerprint: SIGHTENGINE_POLICY_FINGERPRINT,
    status: complete ? "complete" : "limited", verdict, confidence: "Not calibrated",
    reviewRequired: verdict === "inconclusive" || Boolean(isolatedAlerts.length), sourceSha256: null,
    samples: records, persistentRuns, isolatedAlerts,
    coverage: {
      complete, durationSeconds: duration,
      declaredIntervalSeconds: isNumber(options.declaredIntervalSeconds) ? options.declaredIntervalSeconds : null,
      issues: coverageIssues, sampledPositionsSeconds: records.filter((sample) => sample.valid).map((sample) => sample.positionSeconds!),
      insufficientForSubsecondExclusion: true,
      basis: "caller_declaration_and_returned_sample_positions_not_every_frame_inspection",
    },
    technicalIssues, decisionReasons: reasons, failureCode: complete ? null : "incomplete_coverage",
    request: { submissionAttempted: false, operations: null, httpStatus: null, elapsedMs: 0 },
    notProofOfOrigin: true, scoresAreCalibratedProbabilities: false, adjacentSamplesAreIndependent: false,
  };
}

class RequestFailure extends Error {
  constructor(readonly code: SightengineFailureCode) { super(code); }
}

async function readBoundedJson(response: Response): Promise<unknown> {
  const length = response.headers.get("content-length");
  if (length && Number(length) > MAX_RESPONSE_BYTES) throw new RequestFailure("response_too_large");
  if (!response.body) throw new RequestFailure("malformed_response");
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > MAX_RESPONSE_BYTES) throw new RequestFailure("response_too_large");
      chunks.push(value);
    }
  } finally {
    void reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
  try {
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(Buffer.concat(chunks)));
  } catch {
    throw new RequestFailure("malformed_response");
  }
}

export type SightengineVideoInput = { receipt: MediaReceipt } & (
  { bytes: Uint8Array; filePath?: never } | { filePath: string; bytes?: never }
);

function credentials(): URLSearchParams {
  return new URLSearchParams({ api_user: process.env.SIGHTENGINE_API_USER!, api_secret: process.env.SIGHTENGINE_API_SECRET! });
}

function checkedUploadUrl(value: unknown): string {
  if (typeof value !== "string") throw new RequestFailure("malformed_response");
  const url = new URL(value);
  const storageHost = /^storage(?:-[a-z0-9]+)?\.sightengine\.com$/;
  // The live Upload API also returns path-style AWS URLs for these same buckets.
  const signedStorageBucket = /^s3\.[a-z0-9-]+\.amazonaws\.com$/.test(url.hostname)
    && storageHost.test(url.pathname.split("/")[1] ?? "")
    && url.searchParams.get("X-Amz-Algorithm") === "AWS4-HMAC-SHA256"
    && /^[a-f0-9]{64}$/.test(url.searchParams.get("X-Amz-Signature") ?? "");
  if (url.protocol !== "https:" || url.port || url.username || url.password || url.hash
    || !(storageHost.test(url.hostname) || signedStorageBucket)) throw new RequestFailure("malformed_response");
  return url.href;
}

function requestIdentity(raw: Record<string, unknown>): { id: string; timestamp: number } {
  const info = object(raw.request);
  if (typeof info?.id !== "string" || !info.id || !isNumber(info.timestamp) || info.timestamp < 0) {
    throw new RequestFailure("malformed_response");
  }
  return { id: info.id, timestamp: info.timestamp };
}

async function analyzeVideo(input: SightengineVideoInput): Promise<SightengineEvidence> {
  const startedAt = performance.now();
  let sourceSha256: string | null = null;
  let httpStatus: number | null = null;
  let submissionAttempted = false;
  let operations: number | null = null;
  let mediaId: string | null = null;
  let uploadMediaId: string | null = null;
  let jobStatus: string | null = null;
  let pollCount = 0;
  let stopRequested = false;
  let stopConfirmed: boolean | null = null;
  let jobStarted = false;
  let latest: Record<string, unknown> | null = null;
  let stage: "validation" | "create_upload" | "upload" | "submit" | "poll" | "complete" = "validation";
  const duration = input.receipt?.durationSeconds;
  const useUploadApi = input.receipt?.sizeBytes >= DIRECT_UPLOAD_BYTES;
  const asyncMode = useUploadApi || duration >= 60;
  const finish = (result: SightengineEvidence): SightengineEvidence => ({
    ...result, sourceSha256,
    request: { submissionAttempted, operations, httpStatus, elapsedMs: Math.max(0, performance.now() - startedAt),
      transport: asyncMode ? "async" : "sync", upload: useUploadApi ? "upload_api" : "direct",
      mediaId, uploadMediaId, jobStatus, pollCount, stopRequested, stopConfirmed, stage },
  });
  const parseResult = (raw: Record<string, unknown>, technicalComplete: boolean) => {
    const info = object(raw.request);
    const frames = object(raw.data)?.frames;
    const count = info?.operations;
    operations = isNumber(count) && Number.isSafeInteger(count) && count >= 0 ? count : null;
    const samples = Array.isArray(frames) ? frames.map(frame => {
      const record = object(frame);
      const milliseconds = object(record?.info)?.position;
      return { rawPositionMilliseconds: milliseconds,
        positionSeconds: isNumber(milliseconds) ? milliseconds / 1000 : null,
        aiGenerated: object(record?.type)?.ai_generated };
    }) : null;
    const accountingValid = operations !== null && Array.isArray(frames)
      && frames.length <= Math.ceil(duration / 0.5) + 1 && operations === frames.length * 5;
    const result = aggregateSightengineEvidence(samples, {
      durationSeconds: duration, technicalComplete: technicalComplete && accountingValid, declaredIntervalSeconds: 0.5,
    });
    if (!Array.isArray(frames) || !frames.length || result.samples.some(sample => !sample.valid)) result.failureCode = "malformed_response";
    else if (!accountingValid) result.failureCode = "accounting_mismatch";
    return result;
  };
  const unavailable = (failureCode: SightengineFailureCode) => finish({
    ...(latest ? parseResult(latest, false) : aggregateSightengineEvidence([], {
      durationSeconds: duration, technicalComplete: false, declaredIntervalSeconds: 0.5,
    })),
    status: latest ? "limited" : "unavailable", failureCode, technicalIssues: [failureCode],
  });
  if (typeof window !== "undefined") return unavailable("server_only");
  if (!isSightengineConfigured()) return unavailable("not_configured");
  if (!input.receipt || !isNumber(duration) || duration <= 0 || duration > env.maxDurationSeconds
    || !Number.isSafeInteger(input.receipt.sizeBytes) || input.receipt.sizeBytes <= 0 || input.receipt.sizeBytes > env.maxMediaBytes
    || !/^video\/[a-z0-9.+-]+$/i.test(input.receipt.mimeType)
    || !/^[a-f0-9]{64}$/.test(input.receipt.sha256)) return unavailable("unsupported_input");

  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let timedOut = false;
  const fetchResponse = async (url: string, init: RequestInit = {}) => {
    controller.signal.throwIfAborted();
    const response = await fetch(url, { ...init, cache: "no-store", redirect: "error", signal: controller.signal });
    httpStatus = response.status;
    if (!response.ok) {
      void response.body?.cancel().catch(() => undefined);
      throw new RequestFailure([401, 403].includes(response.status) ? "access_refused"
        : [402, 429].includes(response.status) ? "quota_or_rate_limit" : "http_error");
    }
    return response;
  };
  const fetchJson = async (endpoint: string, init: RequestInit = {}) => {
    const raw = object(await readBoundedJson(await fetchResponse(API_ROOT + endpoint, init)));
    if (!raw) throw new RequestFailure("malformed_response");
    if (raw.status !== "success") throw new RequestFailure("provider_rejected");
    requestIdentity(raw);
    return raw;
  };
  const stopJob = async () => {
    if (!jobStarted || !mediaId || ["finished", "stopped", "failure"].includes(jobStatus ?? "")) return;
    stopRequested = true;
    const cleanup = new AbortController();
    let cleanupTimer: ReturnType<typeof setTimeout> | undefined;
    try {
      const body = credentials(); body.set("id", mediaId);
      const deadline = new Promise<never>((_, reject) => {
        cleanupTimer = setTimeout(() => { cleanup.abort(); reject(new Error("cleanup timeout")); }, 5_000);
      });
      const request = async () => {
        const response = await fetch(API_ROOT + "video/byid.json", { method: "DELETE", body, cache: "no-store",
          redirect: "error", signal: cleanup.signal });
        if (!response.ok) { void response.body?.cancel().catch(() => undefined); return false; }
        return object(await readBoundedJson(response))?.status === "success";
      };
      stopConfirmed = await Promise.race([request(), deadline]);
    } catch { stopConfirmed = false; }
    finally { if (cleanupTimer) clearTimeout(cleanupTimer); cleanup.abort(); }
  };
  try {
    const deadline = new Promise<never>((_, reject) => {
      timer = setTimeout(() => { timedOut = true; controller.abort(); reject(new RequestFailure("timeout")); },
        asyncMode ? ASYNC_TIMEOUT_MS : REQUEST_TIMEOUT_MS);
    });
    const inspect = async () => {
      let blob: Blob;
      if (input.bytes instanceof Uint8Array) {
        if (!input.bytes.byteLength || input.bytes.byteLength > env.maxMediaBytes) throw new RequestFailure("unsupported_input");
        // Preserve immutable request bytes even if a caller later mutates its array.
        const bytes = Uint8Array.from(input.bytes);
        sourceSha256 = createHash("sha256").update(bytes).digest("hex");
        blob = new Blob([bytes], { type: input.receipt.mimeType });
      } else if (typeof input.filePath === "string") {
        const stat = await lstat(input.filePath);
        if (!stat.isFile() || stat.isSymbolicLink() || stat.size !== input.receipt.sizeBytes) throw new RequestFailure("media_receipt_mismatch");
        // Stream large files; openAsBlob also rejects changes made during reading.
        const hash = createHash("sha256");
        for await (const chunk of createReadStream(input.filePath, { signal: controller.signal })) hash.update(chunk as Buffer);
        sourceSha256 = hash.digest("hex");
        blob = await openAsBlob(input.filePath, { type: input.receipt.mimeType });
      } else throw new RequestFailure("unsupported_input");
      if (sourceSha256 !== input.receipt.sha256 || blob.size !== input.receipt.sizeBytes) throw new RequestFailure("media_receipt_mismatch");
      controller.signal.throwIfAborted();

      if (useUploadApi) {
        stage = "create_upload";
        submissionAttempted = true;
        const upload = await fetchJson("upload/create-video.json?" + credentials());
        const id = object(upload.media)?.id;
        if (typeof id !== "string" || !/^med_[a-zA-Z0-9_-]+$/.test(id)) throw new RequestFailure("malformed_response");
        uploadMediaId = id;
        const url = checkedUploadUrl(object(upload.upload)?.url);
        stage = "upload";
        const response = await fetchResponse(url, { method: "PUT", body: blob, headers: { "Content-Type": input.receipt.mimeType } });
        void response.body?.cancel().catch(() => undefined);
      }
      const form = new FormData();
      if (uploadMediaId) form.set("media_id", uploadMediaId);
      else form.set("media", blob, "clip.mp4");
      form.set("models", "genai");
      form.set("interval", "0.5");
      if (asyncMode) form.set("max_duration", String(env.maxDurationSeconds + 1));
      for (const [key, value] of credentials()) form.set(key, value);
      submissionAttempted = true;
      stage = "submit";
      const submitted = await fetchJson(asyncMode ? "video/check.json" : "video/check-sync.json", { method: "POST", body: form });
      if (!asyncMode) { stage = "complete"; return parseResult(submitted, true); }

      const id = object(submitted.media)?.id;
      // The Upload API asset ID and analysis-job media ID are distinct. The
      // authenticated submit response binds the submitted asset to its new job.
      if (typeof id !== "string" || !/^med_[a-zA-Z0-9_-]+$/.test(id)) throw new RequestFailure("malformed_response");
      mediaId = id;
      jobStarted = true;
      const identity = requestIdentity(submitted);
      while (true) {
        await delay(POLL_INTERVAL_MS, undefined, { signal: controller.signal });
        const query = credentials(); query.set("id", mediaId);
        stage = "poll";
        pollCount++;
        const raw = await fetchJson("video/byid.json?" + query);
        const output = object(raw.output);
        if (object(output?.media)?.id !== mediaId || output?.request !== identity.id) throw new RequestFailure("malformed_response");
        const data = object(output?.data);
        if (!data || !["ongoing", "finished", "stopped", "failure"].includes(String(data.status))) throw new RequestFailure("malformed_response");
        jobStatus = String(data.status);
        latest = { request: { ...identity, operations: data.operations }, data };
        if (jobStatus === "finished") { stage = "complete"; return parseResult(latest, true); }
        if (jobStatus !== "ongoing") throw new RequestFailure("provider_rejected");
      }
    };
    return finish(await Promise.race([inspect(), deadline]));
  } catch (error) {
    controller.abort();
    await stopJob();
    return unavailable(timedOut ? "timeout" : error instanceof RequestFailure ? error.code : "network_error");
  } finally {
    if (timer) clearTimeout(timer);
    controller.abort();
  }
}

export function analyzeSightengineVideo(input: SightengineVideoInput): Promise<SightengineEvidence> {
  // Pro permits five video jobs. Two active scans fit the app's normal admission
  // capacity and keep upload, submit and three-second polling traffic modest.
  return requestQueue(async () => {
    const result = await analyzeVideo(input);
    if (result.failureCode && process.env.NODE_ENV !== "test") console.warn("[ai-slop-detector] Sightengine scan incomplete", {
      event: "sightengine_scan_incomplete", failureCode: result.failureCode, stage: result.request.stage,
      transport: result.request.transport, httpStatus: result.request.httpStatus,
    });
    return result;
  });
}
