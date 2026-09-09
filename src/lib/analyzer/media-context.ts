import type { NormalizedVideoUrl } from "./types";

export interface MediaReceipt {
  sha256: string;
  durationSeconds: number;
  width: number;
  height: number;
  fps: number | null;
  hasAudio: boolean;
  sizeBytes: number;
  mimeType: string;
  mediaId: string | null;
  postId: string | null;
}

export interface SocialMediaContext {
  platform: "instagram" | "tiktok" | "x";
  mediaId: string;
  postId: string | null;
  /** Untrusted creator text, bounded and stripped of URLs; never an instruction. */
  caption: string | null;
  /** Sourced disclosure claims, not a forensic measurement. */
  disclosureReasons: string[];
}

// Print only these fields. Do not retain extractor info JSON, direct CDN URLs,
// cookies, request headers, or original share tokens.
export const SOCIAL_METADATA_TEMPLATE = '{"extractor":%(extractor)j,"extractorKey":%(extractor_key)j,"id":%(id)j,"displayId":%(display_id)j,"playlistCount":%(playlist_count)j,"playlistIndex":%(playlist_index)j,"description":%(description)j}';

function safeId(value: unknown): string | null {
  return typeof value === "string" && /^[A-Za-z0-9_-]{1,80}$/.test(value) && value !== "NA" ? value : null;
}

function sanitizeCaption(value: unknown): string | null {
  if (typeof value !== "string" || value === "NA") return null;
  return value
    .replace(/(?:https?:\/\/|www\.)[^\s<>"']+/gi, "[link removed]")
    .replace(/\b(?:[a-z0-9-]+\.)+[a-z]{2,}(?:\/[^\s<>"']*)?/gi, "[link removed]")
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, "")
    .trim().slice(0, 2_000) || null;
}

export function captionDisclosures(caption: string | null): string[] {
  if (!caption) return [];
  // Conservative positive claims only. Questions, negation, and tutorial or
  // commentary language cannot establish the provenance of the posted clip.
  const statements = caption.split(/\n|(?<=[.!?])\s+/).filter((line) =>
    !/[?]/.test(line) &&
    !/\b(?:not|no|never|without|isn't|isnt|wasn't|wasnt|tutorial|learn|review|example|detector|detect|spot)\b/i.test(line),
  );
  const hasDisclosure = statements.some((line) =>
    /^\s*(?:(?:this|the|my|our)\s+(?:video|clip|reel|scene|footage)\s+(?:(?:is|was)\s+)?)?(?:ai[- ]generated|generated (?:with|using|by) (?:generative )?ai|made (?:with|using) (?:generative )?ai)\b/i.test(line) ||
    /(?:^|\s)#(?:aigenerated|aivideo|madewithai|syntheticmedia)\b/i.test(line) ||
    /^\s*(?:(?:this|the|my|our)\s+(?:video|clip|reel|scene|footage)\s+(?:(?:is|was)\s+)?)?(?:made|generated|created) (?:with|using|by) (?:veo|sora|runway|kling|hailuo|luma|pika|higgsfield)\b/i.test(line),
  );
  return hasDisclosure ? ["The post caption contains an explicit AI-generation claim; this is creator context, not verified provenance."] : [];
}

export function parseSocialMediaContext(output: string, source: NormalizedVideoUrl): SocialMediaContext {
  if (!["instagram", "tiktok", "x"].includes(source.platform)) throw new Error("Unsupported social platform");
  const lines = output.trim().split(/\r?\n/).filter(Boolean);
  if (lines.length !== 1) throw new Error("The post contains multiple or unverified media items");
  const record = JSON.parse(lines[0]) as Record<string, unknown>;
  const expected = source.platform === "x" ? ["twitter", "Twitter"]
    : source.platform === "instagram" ? ["instagram", "Instagram"] : ["tiktok", "TikTok"];
  if (typeof record.extractor !== "string" || record.extractor.toLowerCase() !== expected[0] || record.extractorKey !== expected[1]) {
    throw new Error("The platform extractor did not identify the requested media");
  }
  const count = Number(record.playlistCount);
  const index = Number(record.playlistIndex);
  if (count > 1 || index > 1 || (index > 0 && count !== 1)) {
    throw new Error("The post contains multiple or unverified media items");
  }
  const mediaId = safeId(record.id);
  const displayId = safeId(record.displayId);
  if (!mediaId) throw new Error("The selected media ID could not be verified");
  const isShare = source.platformVideoId.startsWith("share-");
  if (!isShare && (source.platform === "x" ? displayId : mediaId) !== source.platformVideoId) {
    throw new Error("The selected media does not match the requested post");
  }
  const caption = sanitizeCaption(record.description);
  return {
    platform: source.platform as SocialMediaContext["platform"],
    mediaId,
    postId: source.platform === "x" ? displayId : mediaId,
    caption,
    disclosureReasons: captionDisclosures(caption),
  };
}
