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

export const MEDIA_TYPE_OPTIONS = [
  { value: "video", label: "Video — library root" },
  { value: "audio", label: "Music (audio) — music library" },
] as const;

export type QualityId = (typeof QUALITY_OPTIONS)[number]["value"];
export type MediaTypeId = (typeof MEDIA_TYPE_OPTIONS)[number]["value"];
