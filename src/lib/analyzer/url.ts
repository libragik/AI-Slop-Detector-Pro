import type { NormalizedVideoUrl } from "./types";

export class UnsupportedVideoUrlError extends Error {
  readonly code = "UNSUPPORTED_VIDEO_URL";

  constructor(message = "Use a public YouTube, TikTok, Instagram, or X video URL.") {
    super(message);
    this.name = "UnsupportedVideoUrlError";
  }
}

const YOUTUBE_ID = /^[A-Za-z0-9_-]{11}$/;
const TIKTOK_ID = /^\d{8,24}$/;
const TIKTOK_SHORT_CODE = /^[A-Za-z0-9_-]{4,64}$/;
const INSTAGRAM_CODE = /^[A-Za-z0-9_-]{5,32}$/;
const INSTAGRAM_SHARE_TOKEN = /^[A-Za-z0-9_-]{5,64}$/;
const INSTAGRAM_HANDLE = /^@?[A-Za-z0-9._]{1,30}$/;
const X_STATUS_ID = /^[1-9]\d{0,19}$/;
const X_HANDLE = /^[A-Za-z0-9_]{1,15}$/;

function cleanHost(url: URL): string {
  return url.hostname.toLowerCase().replace(/\.$/, "");
}

function parseHttpUrl(input: string): URL {
  const value = input.trim();
  if (!value || value.length > 2_048) {
    throw new UnsupportedVideoUrlError();
  }

  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new UnsupportedVideoUrlError("That does not look like a complete video URL.");
  }

  if (!["https:", "http:"].includes(url.protocol)) {
    throw new UnsupportedVideoUrlError("Only HTTP and HTTPS video URLs are supported.");
  }
  if (url.username || url.password || url.port) {
    throw new UnsupportedVideoUrlError("Credentials and custom ports are not allowed in video URLs.");
  }
  return url;
}

function youtube(url: URL, inputUrl: string): NormalizedVideoUrl | null {
  const host = cleanHost(url);
  let id: string | null = null;

  if (host === "youtu.be") {
    const parts = url.pathname.split("/").filter(Boolean);
    if (parts.length !== 1) throw new UnsupportedVideoUrlError("The YouTube share URL is invalid.");
    id = parts[0] ?? null;
  } else if (
    host === "youtube.com" ||
    host === "www.youtube.com" ||
    host === "m.youtube.com" ||
    host === "music.youtube.com" ||
    host === "youtube-nocookie.com" ||
    host === "www.youtube-nocookie.com"
  ) {
    const parts = url.pathname.split("/").filter(Boolean);
    if (url.pathname === "/watch") id = url.searchParams.get("v");
    else if (["shorts", "embed", "live"].includes(parts[0] ?? "")) {
      if (parts.length !== 2) throw new UnsupportedVideoUrlError("The YouTube video path is invalid.");
      id = parts[1] ?? null;
    }
  }

  if (!id) return null;
  if (!YOUTUBE_ID.test(id)) {
    throw new UnsupportedVideoUrlError("The YouTube video ID is invalid.");
  }

  return {
    platform: "youtube",
    platformVideoId: id,
    canonicalKey: `youtube:${id}`,
    canonicalUrl: `https://www.youtube.com/watch?v=${id}`,
    inputUrl,
  };
}

function tiktok(url: URL, inputUrl: string): NormalizedVideoUrl | null {
  const host = cleanHost(url);
  const mainHosts = ["tiktok.com", "www.tiktok.com", "m.tiktok.com"];
  const shortHosts = ["vm.tiktok.com", "vt.tiktok.com"];
  if (![...mainHosts, ...shortHosts].includes(host)) return null;

  const parts = url.pathname.split("/").filter(Boolean);
  if (
    mainHosts.includes(host) &&
    parts.length === 3 &&
    parts[0]?.startsWith("@") &&
    parts[1] === "video"
  ) {
    const id = parts[2];
    if (!id || !TIKTOK_ID.test(id)) {
      throw new UnsupportedVideoUrlError("The TikTok video ID is invalid.");
    }
    return {
      platform: "tiktok",
      platformVideoId: id,
      canonicalKey: `tiktok:${id}`,
      canonicalUrl: `https://www.tiktok.com/@_/video/${id}`,
      inputUrl,
    };
  }

  // TikTok's vm/vt hosts and the mobile-app /t/ form contain opaque codes.
  // Keeping the trusted redirect form yields a deterministic cache key without
  // following a redirect in the application process.
  const isShortHostShare = shortHosts.includes(host) && parts.length === 1;
  const isPathShare = host === "www.tiktok.com" && parts.length === 2 && parts[0] === "t";
  if (isShortHostShare || isPathShare) {
    const code = parts[isPathShare ? 1 : 0];
    if (!code || !TIKTOK_SHORT_CODE.test(code)) {
      throw new UnsupportedVideoUrlError("The TikTok share URL is invalid.");
    }
    const canonicalUrl = isPathShare
      ? `https://www.tiktok.com/t/${code}/`
      : `https://${host}/${code}`;
    return {
      platform: "tiktok",
      platformVideoId: `share-${host}-${code}`,
      canonicalKey: `tiktok:share:${host}:${code}`,
      canonicalUrl,
      inputUrl,
    };
  }

  throw new UnsupportedVideoUrlError("Use a TikTok video URL, not a profile or feed URL.");
}

function instagram(url: URL, inputUrl: string): NormalizedVideoUrl | null {
  const host = cleanHost(url);
  if (!["instagram.com", "www.instagram.com", "m.instagram.com"].includes(host)) {
    return null;
  }

  const parts = url.pathname.split("/").filter(Boolean);
  if (parts.length === 3 && parts[0] === "share" && parts[1] === "reel") {
    const token = parts[2];
    if (!token || !INSTAGRAM_SHARE_TOKEN.test(token)) {
      throw new UnsupportedVideoUrlError("The Instagram Reel share token is invalid.");
    }
    return {
      platform: "instagram",
      platformVideoId: `share-reel-${token}`,
      canonicalKey: `instagram:share:reel:${token}`,
      canonicalUrl: `https://www.instagram.com/share/reel/${token}/`,
      inputUrl,
    };
  }

  const mediaKinds = ["reel", "reels", "p", "tv"];
  let kind: string | undefined;
  let code: string | undefined;

  if (parts.length === 2 && mediaKinds.includes(parts[0] ?? "")) {
    kind = parts[0];
    code = parts[1];
  } else if (
    parts.length === 3 &&
    INSTAGRAM_HANDLE.test(parts[0] ?? "") &&
    mediaKinds.includes(parts[1] ?? "")
  ) {
    kind = parts[1];
    code = parts[2];
  } else {
    throw new UnsupportedVideoUrlError("Use an Instagram Reel or video post URL.");
  }

  if (!code || !INSTAGRAM_CODE.test(code)) {
    throw new UnsupportedVideoUrlError("The Instagram post code is invalid.");
  }

  return {
    platform: "instagram",
    platformVideoId: code,
    canonicalKey: `instagram:${code}`,
    canonicalUrl: `https://www.instagram.com/${kind === "p" ? "p" : "reel"}/${code}/`,
    inputUrl,
  };
}

function xStatus(url: URL, inputUrl: string): NormalizedVideoUrl | null {
  const host = cleanHost(url);
  const supportedHosts = new Set([
    "x.com",
    "www.x.com",
    "m.x.com",
    "mobile.x.com",
    "twitter.com",
    "www.twitter.com",
    "m.twitter.com",
    "mobile.twitter.com",
  ]);
  if (!supportedHosts.has(host)) return null;

  const parts = url.pathname.split("/").filter(Boolean);
  let id: string | undefined;

  if (parts.length === 3 && parts[0] === "i" && parts[1] === "status") {
    id = parts[2];
  } else if (
    parts.length >= 3 &&
    X_HANDLE.test(parts[0] ?? "") &&
    parts[1] === "status"
  ) {
    id = parts[2];
    const suffix = parts.slice(3);
    if (
      suffix.length !== 0 &&
      !(
        suffix.length === 2 &&
        ["video", "photo"].includes(suffix[0] ?? "") &&
        /^[1-9]\d*$/.test(suffix[1] ?? "")
      )
    ) {
      throw new UnsupportedVideoUrlError("The X status path is invalid.");
    }
  } else if (
    parts.length === 4 &&
    parts[0] === "i" &&
    parts[1] === "web" &&
    parts[2] === "status"
  ) {
    id = parts[3];
  } else if (parts.length === 2 && parts[0] === "statuses") {
    id = parts[1];
  } else {
    throw new UnsupportedVideoUrlError("Use an X status URL, not a profile or feed URL.");
  }

  if (!id || !X_STATUS_ID.test(id)) {
    throw new UnsupportedVideoUrlError("The X status ID is invalid.");
  }

  return {
    platform: "x",
    platformVideoId: id,
    canonicalKey: `x:${id}`,
    canonicalUrl: `https://x.com/i/status/${id}`,
    inputUrl,
  };
}

export function normalizeVideoUrl(input: string): NormalizedVideoUrl {
  const url = parseHttpUrl(input);
  const original = input.trim();

  const parsed =
    youtube(url, original) ??
    tiktok(url, original) ??
    instagram(url, original) ??
    xStatus(url, original);
  if (!parsed) throw new UnsupportedVideoUrlError();
  // Never retain the submitter's raw URL. It may contain tracking parameters,
  // share tokens, or other user-specific query values. The canonical URL is all
  // the analyzer, public response, and persistent cache need.
  return { ...parsed, inputUrl: parsed.canonicalUrl };
}
