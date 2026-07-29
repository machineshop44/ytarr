"""Named download quality presets → yt-dlp format selectors."""

from __future__ import annotations

QUALITY_PRESETS: dict[str, str] = {
    "best": "bv*+ba/b",
    "2160p": "bv*[height<=2160]+ba/b[height<=2160]/b",
    "1080p": "bv*[height<=1080]+ba/b[height<=1080]/b",
    "720p": "bv*[height<=720]+ba/b[height<=720]/b",
    "480p": "bv*[height<=480]+ba/b[height<=480]/b",
    "worst": "wv*+wa/w",
}

# Audio extract: prefer by approx bitrate (abr), then post-process with --audio-quality.
AUDIO_QUALITY_PRESETS: dict[str, str] = {
    "best": "ba/b",
    "320k": "ba[abr<=320]/ba/b",
    "192k": "ba[abr<=192]/ba/b",
    "128k": "ba[abr<=128]/ba/b",
    "64k": "ba[abr<=64]/ba/b",
    "worst": "wa/w",
}

# Passed to yt-dlp --audio-quality when extracting (0 = best VBR; or bitrate like 192K).
AUDIO_QUALITY_FFMPEG: dict[str, str] = {
    "best": "0",
    "320k": "320K",
    "192k": "192K",
    "128k": "128K",
    "64k": "64K",
    "worst": "9",
}

VIDEO_QUALITY_IDS = (*QUALITY_PRESETS.keys(), "custom")
AUDIO_QUALITY_IDS = (*AUDIO_QUALITY_PRESETS.keys(), "custom")
QUALITY_IDS = tuple(dict.fromkeys((*VIDEO_QUALITY_IDS, *AUDIO_QUALITY_IDS)))


def normalize_quality(quality: str | None, *, media_type: str = "video") -> str:
    q = (quality or "").strip().lower() or "best"
    audio = (media_type or "video").strip().lower() == "audio"
    if audio:
        if q in AUDIO_QUALITY_IDS:
            return q
        # Legacy video preset on a music source → best audio
        if q in VIDEO_QUALITY_IDS:
            return "best"
        return "best"
    if q in VIDEO_QUALITY_IDS:
        return q
    if q in AUDIO_QUALITY_PRESETS:
        return "best"
    return "best"


def resolve_audio_ffmpeg_quality(
    quality: str | None,
    *,
    default_quality: str = "best",
) -> str:
    """yt-dlp --audio-quality value for music extracts."""
    q = (quality or "").strip().lower()
    if not q:
        q = normalize_quality(default_quality, media_type="audio")
    else:
        q = normalize_quality(q, media_type="audio")
    if q == "custom":
        return "0"
    return AUDIO_QUALITY_FFMPEG.get(q, "0")


def resolve_format_selector(
    quality: str | None,
    *,
    default_quality: str = "best",
    custom_format: str = "bv*+ba/b",
    media_type: str = "video",
    default_music_quality: str = "best",
) -> str:
    """Resolve a source quality (or empty = default) to a yt-dlp -f string."""
    audio = (media_type or "video").strip().lower() == "audio"
    q = (quality or "").strip().lower()
    if not q:
        q = normalize_quality(
            default_music_quality if audio else default_quality,
            media_type=media_type,
        )
    else:
        q = normalize_quality(q, media_type=media_type)

    if q == "custom":
        fmt = (custom_format or "").strip() or ("ba/b" if audio else "bv*+ba/b")
        return fmt
    if audio:
        return AUDIO_QUALITY_PRESETS.get(q, "ba/b")
    return QUALITY_PRESETS.get(q, QUALITY_PRESETS["best"])
