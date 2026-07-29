from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..models import MonitoredSource, Video
from . import ytdlp

# Common English/YouTube noise — keep discover tags useful.
_STOP = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "of",
    "to",
    "in",
    "on",
    "for",
    "with",
    "from",
    "by",
    "at",
    "is",
    "it",
    "this",
    "that",
    "these",
    "those",
    "my",
    "your",
    "our",
    "their",
    "video",
    "videos",
    "official",
    "trailer",
    "full",
    "episode",
    "ep",
    "part",
    "vs",
    "watch",
    "new",
    "best",
    "how",
    "what",
    "why",
    "when",
    "where",
    "who",
    "live",
    "stream",
    "shorts",
    "youtube",
    "channel",
    "playlist",
    "music",
    "audio",
    "hd",
    "4k",
    "1080p",
    "720p",
}

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9'&-]{2,}")


@dataclass
class DiscoverHit:
    kind: str
    title: str
    url: str
    id: str | None = None
    channel: str | None = None
    thumbnail_url: str | None = None
    duration: int | None = None
    description: str | None = None
    video_count: int | None = None
    already_added: bool = False


@dataclass
class DiscoverSection:
    tag: str
    source: str  # "library_channel" | "title_tag" | "metadata_tag"
    based_on: str | None
    weight: int
    results: list[DiscoverHit]


def _normalize_tag(raw: str) -> str | None:
    text = re.sub(r"\s+", " ", (raw or "").strip())
    if len(text) < 3 or len(text) > 48:
        return None
    lower = text.lower()
    if lower in _STOP:
        return None
    if lower.isdigit():
        return None
    return text


def _tokens_from_text(text: str) -> list[str]:
    found: list[str] = []
    for match in _TOKEN_RE.findall(text or ""):
        token = match.strip("-'")
        if len(token) < 4:
            continue
        lower = token.lower()
        if lower in _STOP:
            continue
        found.append(token)
    return found


def _library_identity(sources: list[MonitoredSource]) -> tuple[set[str], set[str]]:
    ids: set[str] = set()
    titles: set[str] = set()
    for source in sources:
        if source.yt_id:
            ids.add(source.yt_id.lower())
        titles.add(source.title.strip().lower())
        url = (source.url or "").rstrip("/").lower()
        if url:
            ids.add(url)
            # channel path fragment
            if "/@" in url:
                ids.add(url.split("/@")[-1].split("/")[0])
            if "/channel/" in url:
                ids.add(url.split("/channel/")[-1].split("/")[0])
    return ids, titles


def _is_known(hit: ytdlp.SearchHit, ids: set[str], titles: set[str]) -> bool:
    if hit.id and hit.id.lower() in ids:
        return True
    if hit.title and hit.title.strip().lower() in titles:
        return True
    url = (hit.url or "").rstrip("/").lower()
    if url and url in ids:
        return True
    if hit.id and f"https://www.youtube.com/channel/{hit.id}".lower() in ids:
        return True
    return False


def _mine_local_tags(db: Session, channels: list[MonitoredSource]) -> Counter[str]:
    weights: Counter[str] = Counter()
    channel_ids = [c.id for c in channels]

    for channel in channels:
        # Strong seed: find channels similar to ones you already monitor
        title_tag = _normalize_tag(channel.title)
        if title_tag:
            weights[title_tag] += 8

    if channel_ids:
        videos = (
            db.query(Video)
            .filter(Video.source_id.in_(channel_ids))
            .order_by(Video.id.desc())
            .limit(400)
            .all()
        )
        for video in videos:
            for token in _tokens_from_text(video.title):
                tag = _normalize_tag(token)
                if tag:
                    weights[tag] += 1

    return weights


def _fetch_remote_tags(channel: MonitoredSource) -> list[str]:
    """Best-effort tags/categories from yt-dlp channel metadata."""
    try:
        raw = ytdlp.channel_topic_tags(channel.url)
    except Exception:  # noqa: BLE001
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        tag = _normalize_tag(str(item))
        if not tag:
            continue
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(tag)
    return out[:12]


def discover_from_library(
    db: Session,
    *,
    max_tags: int = 8,
    per_tag: int = 8,
    enrich_remote: bool = True,
) -> list[DiscoverSection]:
    """
    Radarr Discover equivalent: suggest channels from tags/topics in your library.
    """
    channels = (
        db.query(MonitoredSource)
        .filter(MonitoredSource.source_type == "channel")
        .order_by(MonitoredSource.title.asc())
        .all()
    )
    if not channels:
        return []

    all_sources = db.query(MonitoredSource).all()
    known_ids, known_titles = _library_identity(all_sources)

    weights = _mine_local_tags(db, channels)
    sources_by_tag: dict[str, str] = {}
    based_on: dict[str, str | None] = {}

    for channel in channels:
        title_tag = _normalize_tag(channel.title)
        if title_tag:
            sources_by_tag[title_tag.lower()] = "library_channel"
            based_on[title_tag.lower()] = channel.title

    if enrich_remote:
        for channel in channels[:5]:
            for tag in _fetch_remote_tags(channel):
                weights[tag] += 4
                sources_by_tag.setdefault(tag.lower(), "metadata_tag")
                based_on.setdefault(tag.lower(), channel.title)

    # Prefer higher-weight tags; skip ultra-generic one-letter noise already filtered
    ranked = [tag for tag, _ in weights.most_common(max_tags * 2)]
    sections: list[DiscoverSection] = []
    seen_urls: set[str] = set()

    for tag in ranked:
        if len(sections) >= max_tags:
            break
        key = tag.lower()
        source_kind = sources_by_tag.get(key, "title_tag")
        try:
            hits = ytdlp.search_youtube(tag, kind="channel", limit=per_tag + 4)
        except ytdlp.YtDlpError:
            continue

        results: list[DiscoverHit] = []
        for hit in hits:
            url_key = (hit.url or "").rstrip("/").lower()
            if not url_key or url_key in seen_urls:
                continue
            known = _is_known(hit, known_ids, known_titles)
            if known:
                continue
            seen_urls.add(url_key)
            results.append(
                DiscoverHit(
                    kind=hit.kind,
                    title=hit.title,
                    url=hit.url,
                    id=hit.id,
                    channel=hit.channel,
                    thumbnail_url=hit.thumbnail_url,
                    duration=hit.duration,
                    description=hit.description,
                    video_count=hit.video_count,
                    already_added=False,
                )
            )
            if len(results) >= per_tag:
                break

        if not results:
            continue

        sections.append(
            DiscoverSection(
                tag=tag,
                source=source_kind,
                based_on=based_on.get(key),
                weight=int(weights.get(tag, 1)),
                results=results,
            )
        )

    return sections
