export const QUALITY_OPTIONS = [
  { value: "", label: "Default (Settings)" },
  { value: "best", label: "Best available" },
  { value: "2160p", label: "2160p (4K) or lower" },
  { value: "1080p", label: "1080p or lower" },
  { value: "720p", label: "720p or lower" },
  { value: "480p", label: "480p or lower" },
  { value: "worst", label: "Worst (smallest)" },
  { value: "custom", label: "Custom format string" },
] as const;

export const DEFAULT_QUALITY_OPTIONS = [
  { value: "best", label: "Best available" },
  { value: "2160p", label: "2160p (4K) or lower" },
  { value: "1080p", label: "1080p or lower" },
  { value: "720p", label: "720p or lower" },
  { value: "480p", label: "480p or lower" },
  { value: "worst", label: "Worst (smallest)" },
  { value: "custom", label: "Custom format string" },
] as const;

/** Per-source / Add New quality when Media type is Music. */
export const MUSIC_QUALITY_OPTIONS = [
  { value: "", label: "Default (Settings)" },
  { value: "best", label: "Best available" },
  { value: "320k", label: "320 kbps or lower" },
  { value: "192k", label: "192 kbps or lower" },
  { value: "128k", label: "128 kbps or lower" },
  { value: "64k", label: "64 kbps or lower" },
  { value: "worst", label: "Worst (smallest)" },
  { value: "custom", label: "Custom format string" },
] as const;

/** Settings → Quality default for music downloads. */
export const DEFAULT_MUSIC_QUALITY_OPTIONS = [
  { value: "best", label: "Best available" },
  { value: "320k", label: "320 kbps or lower" },
  { value: "192k", label: "192 kbps or lower" },
  { value: "128k", label: "128 kbps or lower" },
  { value: "64k", label: "64 kbps or lower" },
  { value: "worst", label: "Worst (smallest)" },
  { value: "custom", label: "Custom format string" },
] as const;

export const MEDIA_TYPE_OPTIONS = [
  { value: "video", label: "Video — library root" },
  { value: "audio", label: "Music (audio) — music library" },
] as const;

export type QualityId = (typeof QUALITY_OPTIONS)[number]["value"];
export type MusicQualityId = (typeof MUSIC_QUALITY_OPTIONS)[number]["value"];
export type MediaTypeId = (typeof MEDIA_TYPE_OPTIONS)[number]["value"];

const VIDEO_QUALITY_VALUES = new Set<string>(QUALITY_OPTIONS.map((o) => o.value));
const MUSIC_QUALITY_VALUES = new Set<string>(MUSIC_QUALITY_OPTIONS.map((o) => o.value));

export function qualityOptionsFor(mediaType: string) {
  return (mediaType || "video").trim().toLowerCase() === "audio"
    ? MUSIC_QUALITY_OPTIONS
    : QUALITY_OPTIONS;
}

/** Drop incompatible preset when switching Video ↔ Music (keep Default / best / worst / custom). */
export function coerceQualityForMedia(quality: string, mediaType: string): string {
  const q = (quality || "").trim().toLowerCase();
  if (!q) return "";
  const audio = (mediaType || "video").trim().toLowerCase() === "audio";
  const allowed = audio ? MUSIC_QUALITY_VALUES : VIDEO_QUALITY_VALUES;
  if (allowed.has(q)) return q;
  if (q === "best" || q === "worst" || q === "custom") return q;
  return "";
}

export function qualityLabel(quality: string | undefined, mediaType?: string): string {
  const q = (quality || "").trim().toLowerCase();
  if (!q || q === "best") return "Any";
  const opts = qualityOptionsFor(mediaType || "video");
  const hit = opts.find((o) => o.value === q);
  return hit?.label ?? q;
}
