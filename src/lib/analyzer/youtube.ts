import { env } from "@/lib/config/env";
import { analyzeCommentsWithGemini, type CommentForAnalysis } from "./gemini";
import type { CommentAnalysis, YoutubeContext, YoutubeMetadata } from "./types";

const YOUTUBE_API = "https://www.googleapis.com/youtube/v3";

interface YoutubeVideoResponse {
  items?: Array<{
    snippet?: {
      title?: string;
      description?: string;
      channelId?: string;
      channelTitle?: string;
      publishedAt?: string;
      thumbnails?: Record<string, { url?: string }>;
    };
    status?: { containsSyntheticMedia?: boolean };
    contentDetails?: { duration?: string };
  }>;
}

interface YoutubeCommentsResponse {
  items?: Array<{
    snippet?: {
      topLevelComment?: {
        snippet?: {
          textDisplay?: string;
          authorChannelId?: { value?: string };
        };
      };
    };
  }>;
  error?: { errors?: Array<{ reason?: string }> };
}

async function youtubeFetch<T>(path: string, params: Record<string, string>): Promise<T> {
  if (!env.youtubeApiKey) throw new Error("YOUTUBE_API_KEY is not configured");
  const url = new URL(`${YOUTUBE_API}/${path}`);
  for (const [key, value] of Object.entries(params)) url.searchParams.set(key, value);
  url.searchParams.set("key", env.youtubeApiKey);

  const response = await fetch(url, {
    signal: AbortSignal.timeout(10_000),
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as YoutubeCommentsResponse | null;
    const reason = body?.error?.errors?.[0]?.reason;
    const error = new Error(`YouTube API returned ${response.status}${reason ? ` (${reason})` : ""}`);
    Object.assign(error, { status: response.status, reason });
    throw error;
  }
  return (await response.json()) as T;
}

const DISCLOSURE_PATTERNS: Array<[RegExp, string]> = [
  [/\b(?:ai|artificial intelligence)[ -]generated\b/i, "Description says AI-generated"],
  [/\bgenerated (?:using|with|by) (?:generative )?(?:ai|artificial intelligence)\b/i, "Description discloses an AI generator"],
  [/\bmade (?:using|with) (?:generative )?(?:ai|artificial intelligence)\b/i, "Description says it was made with AI"],
  [/\b(?:synthetic media|synthetic video|ai[ -]altered|ai[ -]created)\b/i, "Description discloses synthetic or altered media"],
  [/#(?:aigenerated|syntheticmedia)\b/i, "Description contains an explicit synthetic-media hashtag"],
  [/\bmade (?:using|with) (?:veo|sora|runway|kling|hailuo|luma|pika|higgsfield)\b/i, "Description names an AI video generator"],
];

export function findAiDisclosures(title: string, description: string): string[] {
  const explicitTitle = /^\s*[\[(]?(?:ai[ -]generated|synthetic media|made with (?:veo|sora|runway|kling))[\])]?\s*[:|-]/i.test(title)
    ? ["Title explicitly labels the video as synthetic"]
    : [];
  const lines = description.split(/\r?\n/).filter((line) => {
    if (/\?/.test(line) && /\b(?:is|was|could|might).{0,30}(?:ai[ -]generated|synthetic)\b/i.test(line)) return false;
    if (/\b(?:not|no|never|without)\b.{0,30}\b(?:ai[ -]generated|generated (?:using|with|by) (?:generative )?ai|synthetic media)\b/i.test(line)) return false;
    return true;
  });
  const text = lines.join("\n");
  return [
    ...explicitTitle,
    ...DISCLOSURE_PATTERNS.filter(([pattern]) => pattern.test(text)).map(([, reason]) => reason),
  ];
}

async function fetchMetadata(videoId: string): Promise<YoutubeMetadata> {
  const data = await youtubeFetch<YoutubeVideoResponse>("videos", {
    part: "snippet,status,contentDetails",
    id: videoId,
  });
  const video = data.items?.[0];
  if (!video) throw Object.assign(new Error("YouTube video was not found or is not public"), { status: 404 });

  const title = video.snippet?.title ?? "";
  const description = video.snippet?.description ?? "";
  const containsSyntheticMedia = video.status?.containsSyntheticMedia === true;
  const disclosureReasons = findAiDisclosures(title, description);
  if (containsSyntheticMedia) disclosureReasons.unshift("YouTube creator disclosure marks altered or synthetic media");
  const thumbnails = video.snippet?.thumbnails ?? {};
  const thumbnailUrl =
    thumbnails.maxres?.url ??
    thumbnails.standard?.url ??
    thumbnails.high?.url ??
    thumbnails.medium?.url ??
    thumbnails.default?.url ??
    null;

  return {
    title: title || null,
    description: description || null,
    channelId: video.snippet?.channelId ?? null,
    channelTitle: video.snippet?.channelTitle ?? null,
    thumbnailUrl,
    publishedAt: video.snippet?.publishedAt ?? null,
    duration: video.contentDetails?.duration ?? null,
    containsSyntheticMedia,
    hasExplicitAiDisclosure: disclosureReasons.length > 0,
    disclosureReasons,
  };
}

async function fetchComments(videoId: string, creatorChannelId: string | null): Promise<CommentForAnalysis[]> {
  const data = await youtubeFetch<YoutubeCommentsResponse>("commentThreads", {
    part: "snippet",
    videoId,
    maxResults: String(env.youtubeCommentLimit),
    order: "relevance",
    textFormat: "plainText",
  });

  return (data.items ?? []).flatMap((item) => {
    const snippet = item.snippet?.topLevelComment?.snippet;
    const text = snippet?.textDisplay?.trim();
    if (!text) return [];
    return [{ text, isCreator: Boolean(creatorChannelId && snippet?.authorChannelId?.value === creatorChannelId) }];
  });
}

const unavailableComments = (reason: string, status: CommentAnalysis["status"] = "unavailable"): CommentAnalysis => ({
  status,
  sampleSize: 0,
  commentsClaimingAi: 0,
  commentsClaimingReal: 0,
  creatorAdmissionFound: false,
  credibleSourceClaimFound: false,
  commentSummary: "Comment evidence was not included in the score.",
  reason,
});

export async function analyzeYoutubeContext(videoId: string): Promise<YoutubeContext> {
  if (!env.youtubeApiKey) {
    return {
      status: "unavailable",
      metadata: null,
      comments: unavailableComments("YOUTUBE_API_KEY is not configured"),
      reason: "YouTube metadata and comments are disabled until YOUTUBE_API_KEY is configured.",
    };
  }

  try {
    const metadata = await fetchMetadata(videoId);
    let comments: CommentAnalysis;
    try {
      const sample = await fetchComments(videoId, metadata.channelId);
      comments = await analyzeCommentsWithGemini(sample);
    } catch (error) {
      const reason = (error as { reason?: string }).reason;
      comments = reason === "commentsDisabled"
        ? unavailableComments("Comments are disabled for this video.", "comments_disabled")
        : unavailableComments("YouTube comment analysis failed; it did not affect the result.", "failed");
    }
    return { status: "complete", metadata, comments };
  } catch (error) {
    return {
      status: "failed",
      metadata: null,
      comments: unavailableComments("YouTube metadata was unavailable.", "failed"),
      reason: error instanceof Error ? error.message : "YouTube lookup failed",
    };
  }
}
