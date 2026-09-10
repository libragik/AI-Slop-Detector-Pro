import { createHash } from "node:crypto";
import { createReadStream, createWriteStream } from "node:fs";
import { lstat, mkdtemp, readdir, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { extname, join } from "node:path";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";
import { spawn } from "node:child_process";

import { fileTypeFromFile } from "file-type";
import { env } from "@/lib/config/env";
import type { NormalizedVideoUrl } from "./types";
import { normalizeVideoUrl } from "./url";
import { parseSocialMediaContext, SOCIAL_METADATA_TEMPLATE, type MediaReceipt, type SocialMediaContext } from "./media-context";
export type { MediaReceipt, SocialMediaContext } from "./media-context";

export class MediaRetrievalError extends Error {
  readonly code = "MEDIA_RETRIEVAL_FAILED";
  readonly retryable = true;

  constructor(message = "We could not retrieve this video. Save it and use the upload fallback.") {
    super(message);
    this.name = "MediaRetrievalError";
  }
}

export interface TemporaryMedia {
  filePath: string;
  mimeType: string;
  size: number;
  sha256: string;
  receipt: MediaReceipt;
  context: SocialMediaContext | null;
  cleanup: () => Promise<void>;
}

const MAX_YT_DLP_STDERR_BYTES = 4_096;
const MAX_METADATA_STDOUT_BYTES = 65_536;
const INSTAGRAM_UNAVAILABLE_MESSAGE =
  "This Instagram post is unavailable to the scanner. It may be private, deleted, or the share link may have expired. If you can still view it, save the video and upload the file instead.";

function retrievalError(platform: NormalizedVideoUrl["platform"], stderr: Buffer): MediaRetrievalError {
  const diagnostic = stderr
    .toString("utf8")
    .replace(/https?:\/\/[^\s"'<>]+/gi, "[url]")
    .toLowerCase();
  const instagramUnavailable = platform === "instagram" && [
    /\binstagram sent an empty media response\b/,
    /\bprivate\b/,
    /\bdeleted\b/,
    /\bexpired\b/,
    /\bnot available\b/,
    /\bunavailable\b/,
    /\bno longer available\b/,
    /\bdoes not exist\b/,
    /\b(?:post|page|content|media|video)\b[^\n]{0,80}\bremoved\b/,
    /\b404\b[^\n]{0,40}\bnot found\b/,
    /\blogin required\b/,
    /\blog in (?:to|for)\b/,
    /\bregistered users\b/,
    /\bpermission to view\b/,
  ].some((pattern) => pattern.test(diagnostic));

  return new MediaRetrievalError(
    instagramUnavailable ? INSTAGRAM_UNAVAILABLE_MESSAGE : undefined,
  );
}

function run(
  command: string,
  args: string[],
  timeoutMs: number,
  platform: NormalizedVideoUrl["platform"],
): Promise<string> {
  return new Promise((resolve, reject) => {
    const detached = process.platform !== "win32";
    const isWindowsCmd = process.platform === "win32" && /\.(cmd|bat)$/i.test(command);
    const child = spawn(command, args, {
      detached,
      shell: isWindowsCmd,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stderr = Buffer.alloc(0);
    let stdout = "";
    let settled = false;
    const finish = (callback: () => void) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      callback();
    };
    const timer = setTimeout(() => {
      try {
        if (detached && child.pid) process.kill(-child.pid, "SIGKILL");
        else child.kill("SIGKILL");
      } catch {
        child.kill("SIGKILL");
      }
      finish(() => reject(new MediaRetrievalError("Video retrieval timed out. Save the video and use the upload fallback.")));
    }, timeoutMs);

    child.stdout.on("data", (chunk: Buffer) => {
      if (Buffer.byteLength(stdout) + chunk.length > MAX_METADATA_STDOUT_BYTES) {
        try { if (detached && child.pid) process.kill(-child.pid, "SIGKILL"); else child.kill("SIGKILL"); } catch { child.kill("SIGKILL"); }
        finish(() => reject(new MediaRetrievalError("The video metadata exceeded the safe inspection limit. Upload the intended video instead.")));
      } else stdout += chunk.toString("utf8");
    });

    child.stderr.on("data", (chunk: Buffer | string) => {
      const remaining = MAX_YT_DLP_STDERR_BYTES - stderr.length;
      if (remaining <= 0) return;
      const data = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
      stderr = Buffer.concat([stderr, data.subarray(0, remaining)]);
    });
    child.once("error", (error) => {
      finish(() => reject(new MediaRetrievalError((error as NodeJS.ErrnoException).code === "ENOENT" ? "Video retrieval is not installed on this server." : undefined)));
    });
    child.once("close", (code) => {
      finish(() => {
        if (code === 0) resolve(stdout);
        else reject(retrievalError(platform, stderr));
      });
    });
  });
}

type DownloadCommandRunner = (
  command: string,
  args: string[],
  timeoutMs: number,
  platform: NormalizedVideoUrl["platform"],
) => Promise<string | void>;

type MetadataCommandRunner = (
  command: string,
  args: string[],
  timeoutMs: number,
  platform?: NormalizedVideoUrl["platform"],
) => Promise<string>;

const runForOutput: MetadataCommandRunner = (command, args, timeoutMs, platform) => {
  if (platform) return run(command, args, timeoutMs, platform);
  return new Promise((resolve, reject) => {
    const detached = process.platform !== "win32";
    const child = spawn(command, args, {
      detached,
      shell: false,
      windowsHide: true,
      stdio: ["ignore", "pipe", "ignore"],
    });
    let output = "";
    let settled = false;
    const finish = (callback: () => void) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      callback();
    };
    const timer = setTimeout(() => {
      try {
        if (detached && child.pid) process.kill(-child.pid, "SIGKILL");
        else child.kill("SIGKILL");
      } catch {
        child.kill("SIGKILL");
      }
      finish(() => reject(new MediaRetrievalError("YouTube duration verification timed out. Try again or upload the video.")));
    }, timeoutMs);

    child.stdout.on("data", (chunk) => {
      if (output.length < 1_000) output += String(chunk).slice(0, 1_000 - output.length);
    });
    child.once("error", (error) => {
      finish(() => reject(new MediaRetrievalError(
        (error as NodeJS.ErrnoException).code === "ENOENT"
          ? "YouTube duration verification is not installed on this server. Upload the video instead."
          : "The YouTube video duration could not be verified. Try again or upload the video.",
      )));
    });
    child.once("close", (code) => {
      finish(() => {
        if (code === 0) resolve(output);
        else reject(new MediaRetrievalError("The YouTube video duration could not be verified. Try again or upload the video."));
      });
    });
  });
};

export async function verifyYoutubeDuration(
  source: NormalizedVideoUrl,
  commandRunner: MetadataCommandRunner = runForOutput,
): Promise<number> {
  if (source.platform !== "youtube") {
    throw new MediaRetrievalError("Duration verification expected a YouTube URL.");
  }
  const args = [
    "--ignore-config",
    "--no-playlist",
    "--skip-download",
    "--no-write-info-json",
    "--no-write-playlist-metafiles",
    "--no-write-comments",
    "--no-write-thumbnail",
    "--no-write-subs",
    "--no-write-auto-subs",
    "--no-write-description",
    "--print",
    "%(duration)s",
    "--",
    source.canonicalUrl,
  ];
  const output = await commandRunner(
    env.ytDlpPath,
    args,
    Math.min(env.ytDlpTimeoutMs, 30_000),
  );
  const lines = output.trim().split(/\r?\n/).filter(Boolean);
  if (lines.length !== 1) {
    throw new MediaRetrievalError("The YouTube video duration could not be verified. Try again or upload the video.");
  }
  const duration = Number(lines[0]);
  if (!Number.isFinite(duration) || duration <= 0) {
    throw new MediaRetrievalError("The YouTube video duration could not be verified. Try again or upload the video.");
  }
  if (duration > env.maxDurationSeconds) {
    throw new MediaRetrievalError(`This YouTube video is longer than ${env.maxDurationSeconds} seconds. Upload a shorter video instead.`);
  }
  return duration;
}

const X_MEDIA_UNAVAILABLE_MESSAGE =
  "This X status does not contain a directly downloadable X video. Save the intended video and upload the file instead.";

async function readMediaMetadata(
  source: NormalizedVideoUrl,
  commandRunner: MetadataCommandRunner,
  template: string,
): Promise<string> {
  const args = [
    "--ignore-config",
    "--no-cache-dir",
    "--output-na-placeholder", "null",
    "--no-playlist",
    "--playlist-end", "2",
    "--abort-on-error",
    "--socket-timeout", "10",
    "--retries", "1",
    "--extractor-retries", "1",
    "--skip-download",
    "--no-write-info-json",
    "--no-write-playlist-metafiles",
    "--no-write-comments",
    "--no-write-thumbnail",
    "--no-write-subs",
    "--no-write-auto-subs",
    "--no-write-description",
    "--print", template,
    ...(source.platform === "youtube" ? ["--use-extractors", "youtube"] : []),
    "--",
    source.canonicalUrl,
  ];

  try {
    const metadataTimeout =
      source.platform === "tiktok"
        ? Math.min(env.ytDlpTimeoutMs, 30_000)
        : Math.min(env.ytDlpTimeoutMs, 15_000);
    return await commandRunner(
      env.ytDlpPath,
      args,
      metadataTimeout,
      source.platform,
    );
  } catch (error) {
    if (source.platform === "x") throw new MediaRetrievalError(X_MEDIA_UNAVAILABLE_MESSAGE);
    if (error instanceof MediaRetrievalError) throw error;
    throw new MediaRetrievalError("The platform could not verify a single video for this post. Upload the intended clip instead.");
  }

}

async function verifySocialMedia(
  source: NormalizedVideoUrl,
  commandRunner: MetadataCommandRunner,
): Promise<SocialMediaContext> {
  const output = await readMediaMetadata(source, commandRunner, SOCIAL_METADATA_TEMPLATE);
  try {
    return parseSocialMediaContext(output, source);
  } catch {
    throw new MediaRetrievalError(source.platform === "x" ? X_MEDIA_UNAVAILABLE_MESSAGE
      : "This post does not identify one matching video. Multi-item posts are not supported; upload the intended clip instead.");
  }
}

// Deliberately excludes titles, captions, URLs, headers and other source context.
const YOUTUBE_METADATA_TEMPLATE = '{"extractor":%(extractor)j,"extractorKey":%(extractor_key)j,"id":%(id)j,"duration":%(duration)j,"filesize":%(filesize)j,"filesizeApprox":%(filesize_approx)j,"isLive":%(is_live)j,"liveStatus":%(live_status)j,"playlistCount":%(playlist_count)j,"playlistIndex":%(playlist_index)j}';

interface DownloadIdentity {
  mediaId: string;
  postId: string | null;
  context: SocialMediaContext | null;
}

function parseYoutubeMedia(output: string, source: NormalizedVideoUrl): DownloadIdentity {
  try {
    const lines = output.trim().split(/\r?\n/).filter(Boolean);
    if (lines.length !== 1) throw new Error();
    const record = JSON.parse(lines[0]) as Record<string, unknown>;
    if (record.extractor !== "youtube" || record.extractorKey !== "Youtube" ||
        record.id !== source.platformVideoId || !/^[A-Za-z0-9_-]{11}$/.test(String(record.id))) throw new Error();
    // A canonical watch URL must resolve to one ordinary video, never a live
    // stream, pending premiere or playlist selection with ambiguous identity.
    if (record.isLive !== false ||
        (record.liveStatus != null && !["not_live", "was_live"].includes(String(record.liveStatus)))) throw new Error();
    for (const key of ["playlistCount", "playlistIndex"] as const) {
      if (record[key] != null && record[key] !== 1) throw new Error();
    }
    if (record.playlistIndex === 1 && record.playlistCount !== 1) throw new Error();
    if (typeof record.duration !== "number" || !Number.isFinite(record.duration) ||
        record.duration <= 0 || record.duration > env.maxDurationSeconds) throw new Error();
    for (const key of ["filesize", "filesizeApprox"] as const) {
      const size = record[key];
      if (size != null && (typeof size !== "number" || !Number.isFinite(size) || size <= 0 || size > env.maxMediaBytes)) throw new Error();
    }
    return { mediaId: source.platformVideoId, postId: source.platformVideoId, context: null };
  } catch {
    throw new MediaRetrievalError("YouTube could not verify one matching, non-live video within the media limits. Upload the intended clip instead.");
  }
}

type MediaProbe = Pick<MediaReceipt, "durationSeconds" | "width" | "height" | "fps" | "hasAudio">;

export function parseMediaProbe(output: string): MediaProbe {
  const data = JSON.parse(output) as { format?: { duration?: string }; streams?: Array<{ codec_type?: string; width?: number; height?: number; avg_frame_rate?: string }> };
  const streams = Array.isArray(data.streams) ? data.streams : [];
  const video = streams.find((stream) => stream.codec_type === "video");
  const durationSeconds = Number(data.format?.duration);
  const width = Number(video?.width);
  const height = Number(video?.height);
  if (!Number.isFinite(durationSeconds) || durationSeconds <= 0 || !Number.isInteger(width) || width <= 0 || !Number.isInteger(height) || height <= 0) {
    throw new MediaRetrievalError("The video duration and dimensions could not be verified.");
  }
  const [numerator, denominator = "1"] = (video?.avg_frame_rate ?? "").split("/");
  const rate = Number(numerator) / Number(denominator);
  return { durationSeconds, width, height, fps: Number.isFinite(rate) && rate > 0 ? rate : null, hasAudio: streams.some((stream) => stream.codec_type === "audio") };
}

function probeMedia(filePath: string): Promise<MediaProbe> {
  return new Promise((resolve, reject) => {
    const child = spawn(
      env.ffprobePath,
      [
        "-v", "error",
        "-show_entries", "format=duration:stream=codec_type,width,height,avg_frame_rate",
        "-of", "json",
        "--",
        filePath,
      ],
      { shell: false, windowsHide: true, stdio: ["ignore", "pipe", "ignore"] },
    );
    let output = "";
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      reject(new MediaRetrievalError("The video duration could not be verified."));
    }, 10_000);
    child.stdout.on("data", (chunk) => {
      if (output.length + String(chunk).length > MAX_METADATA_STDOUT_BYTES) {
        child.kill("SIGKILL");
        clearTimeout(timer);
        reject(new MediaRetrievalError("The media contains too many streams to inspect safely."));
      } else output += String(chunk);
    });
    child.once("error", () => {
      clearTimeout(timer);
      reject(new MediaRetrievalError("Video duration inspection is not installed on this server."));
    });
    child.once("close", (code) => {
      clearTimeout(timer);
      if (code !== 0) {
        reject(new MediaRetrievalError("The video duration could not be verified."));
      } else {
        try { resolve(parseMediaProbe(output)); } catch { reject(new MediaRetrievalError("The video duration and dimensions could not be verified.")); }
      }
    });
  });
}

async function sha256File(filePath: string): Promise<string> {
  const hash = createHash("sha256");
  for await (const chunk of createReadStream(filePath)) hash.update(chunk as Buffer);
  return hash.digest("hex");
}

async function validateMedia(filePath: string, directory: string, context: SocialMediaContext | null = null): Promise<TemporaryMedia> {
  const info = await lstat(filePath);
  if (!info.isFile() || info.isSymbolicLink()) throw new MediaRetrievalError("The retrieved media was not a regular file.");
  if (info.size <= 0 || info.size > env.maxMediaBytes) throw new MediaRetrievalError("The video is empty or exceeds the upload limit.");

  const detected = await fileTypeFromFile(filePath);
  const mimeType = detected?.mime?.startsWith("video/") ? detected.mime : undefined;
  if (!mimeType) throw new MediaRetrievalError("The retrieved file is not a supported video format.");
  const probe = await probeMedia(filePath);
  if (probe.durationSeconds > env.maxDurationSeconds) {
    throw new MediaRetrievalError(`Upload a video that is ${env.maxDurationSeconds} seconds or shorter.`);
  }

  const sha256 = await sha256File(filePath);
  return {
    filePath,
    mimeType,
    size: info.size,
    sha256,
    receipt: { sha256, ...probe, sizeBytes: info.size, mimeType, mediaId: context?.mediaId ?? null, postId: context?.postId ?? null },
    context,
    cleanup: () => rm(directory, { recursive: true, force: true }),
  };
}

function validateDownloadSource(source: NormalizedVideoUrl): NormalizedVideoUrl {
  // This exported helper is a process boundary. Re-normalize and compare the
  // source so a caller cannot make yt-dlp fetch an arbitrary URL by forging a
  // NormalizedVideoUrl object.
  let normalized: NormalizedVideoUrl;
  try {
    normalized = normalizeVideoUrl(source.canonicalUrl);
  } catch {
    throw new MediaRetrievalError("The video URL failed validation.");
  }
  if (
    normalized.platform !== source.platform ||
    normalized.platformVideoId !== source.platformVideoId ||
    normalized.canonicalKey !== source.canonicalKey ||
    normalized.canonicalUrl !== source.canonicalUrl
  ) {
    throw new MediaRetrievalError("The video URL failed validation.");
  }
  return normalized;
}

export async function downloadSocialVideo(
  source: NormalizedVideoUrl,
  commandRunner: DownloadCommandRunner = run,
  metadataCommandRunner: MetadataCommandRunner = runForOutput,
): Promise<TemporaryMedia> {
  if (!["tiktok", "instagram", "x"].includes(source.platform)) {
    throw new MediaRetrievalError("This platform cannot be downloaded for local media analysis.");
  }
  const normalized = validateDownloadSource(source);
  // Verify native platform media and a single selected item before downloading.
  // This also blocks X posts that redirect to unrelated outbound article media.
  const context = await verifySocialMedia(normalized, metadataCommandRunner);
  return downloadVerifiedMedia(normalized, commandRunner, SOCIAL_METADATA_TEMPLATE, context, (output) => {
    const downloaded = parseSocialMediaContext(output, normalized);
    return { mediaId: downloaded.mediaId, postId: downloaded.postId, context: downloaded };
  });
}

export async function downloadYoutubeVideo(
  source: NormalizedVideoUrl,
  commandRunner: DownloadCommandRunner = run,
  metadataCommandRunner: MetadataCommandRunner = runForOutput,
): Promise<TemporaryMedia> {
  if (source.platform !== "youtube") throw new MediaRetrievalError("YouTube retrieval expected a YouTube URL.");
  const normalized = validateDownloadSource(source);
  const identity = parseYoutubeMedia(await readMediaMetadata(normalized, metadataCommandRunner, YOUTUBE_METADATA_TEMPLATE), normalized);
  return downloadVerifiedMedia(normalized, commandRunner, YOUTUBE_METADATA_TEMPLATE, identity,
    (output) => parseYoutubeMedia(output, normalized));
}

async function downloadVerifiedMedia(
  source: NormalizedVideoUrl,
  commandRunner: DownloadCommandRunner,
  metadataTemplate: string,
  expectedIdentity: Pick<DownloadIdentity, "mediaId" | "postId">,
  parseDownloaded: (output: string) => DownloadIdentity,
): Promise<TemporaryMedia> {
  const directory = await mkdtemp(join(tmpdir(), "ai-slop-detector-"));
  const outputTemplate = join(directory, "video.%(ext)s");
  const args = [
    "--ignore-config",
    "--no-cache-dir",
    "--output-na-placeholder", "null",
    "--no-playlist",
    "--playlist-end", "2",
    "--abort-on-error",
    "--socket-timeout", "15",
    "--retries", "1",
    "--fragment-retries", "1",
    "--extractor-retries", "1",
    "--max-filesize", String(env.maxMediaBytes),
    "--match-filter", `!is_live & duration<=?${env.maxDurationSeconds}`,
    "--format", source.platform === "instagram" ? "b/bv*+ba" : "bv*+ba/b",
    "--merge-output-format", "mp4",
    "--no-write-info-json",
    "--no-write-playlist-metafiles",
    "--no-write-comments",
    "--no-write-thumbnail",
    "--no-write-subs",
    "--no-write-auto-subs",
    "--no-write-description",
    "--no-overwrites",
    "--no-continue",
    "--output", outputTemplate,
    "--print", `after_move:${metadataTemplate}`,
    ...(source.platform === "x" ? ["--use-extractors", "twitter"] :
      source.platform === "youtube" ? ["--use-extractors", "youtube"] : []),
    "--",
    source.canonicalUrl,
  ];

  try {
    const downloadedMetadata = await commandRunner(env.ytDlpPath, args, env.ytDlpTimeoutMs, source.platform);
    const downloadedIdentity = parseDownloaded(downloadedMetadata ?? "");
    if (downloadedIdentity.mediaId !== expectedIdentity.mediaId || downloadedIdentity.postId !== expectedIdentity.postId) {
      throw new MediaRetrievalError("The downloaded media changed after inspection. Upload the intended clip instead.");
    }
    const entries = await readdir(directory);
    const files: Array<{ path: string; size: number }> = [];
    for (const entry of entries) {
      if (entry.endsWith(".part") || entry.endsWith(".ytdl")) continue;
      const path = join(directory, entry);
      const info = await stat(path);
      if (info.isFile()) files.push({ path, size: info.size });
    }
    if (files.length !== 1) throw new MediaRetrievalError("The download did not produce one unambiguous video. Upload the intended clip instead.");
    const media = await validateMedia(files[0].path, directory, downloadedIdentity.context);
    media.receipt.mediaId = downloadedIdentity.mediaId;
    media.receipt.postId = downloadedIdentity.postId;
    return media;
  } catch (error) {
    await rm(directory, { recursive: true, force: true });
    if (error instanceof MediaRetrievalError) throw error;
    throw new MediaRetrievalError();
  }
}

export async function saveUploadedVideo(file: File): Promise<TemporaryMedia> {
  if (file.size <= 0 || file.size > env.maxMediaBytes) {
    throw new MediaRetrievalError(`Upload a non-empty video up to ${Math.floor(env.maxMediaBytes / 1_000_000)} MB.`);
  }

  const directory = await mkdtemp(join(tmpdir(), "ai-slop-upload-"));
  const suffix = extname(file.name).toLowerCase().replace(/[^.a-z0-9]/g, "").slice(0, 8) || ".bin";
  const filePath = join(directory, `upload${suffix}`);

  try {
    const stream = Readable.fromWeb(file.stream() as never);
    await pipeline(stream, createWriteStream(filePath, { flags: "wx", mode: 0o600 }));
    return await validateMedia(filePath, directory);
  } catch (error) {
    await rm(directory, { recursive: true, force: true });
    if (error instanceof MediaRetrievalError) throw error;
    throw new MediaRetrievalError("The uploaded video could not be read.");
  }
}
