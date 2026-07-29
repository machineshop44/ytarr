from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import get_config
from ..models import MonitoredSource, Video, VideoStatus
from . import downloader, ytdlp

# new  = first sync marks existing as seen; later uploads download
# all  = first sync queues entire catalog + keep monitoring new
# video = one-shot single video download (no ongoing channel monitor)
VALID_MODES = {"new", "all", "video"}


def ensure_artwork(db: Session, source: MonitoredSource) -> MonitoredSource:
    cfg = get_config()
    folder = Path(cfg.library_root) / source.folder_name
    folder.mkdir(parents=True, exist_ok=True)
    poster, fanart = ytdlp.fetch_channel_artwork(source.url, folder)
    if poster:
        source.poster_path = str(poster)
    if fanart:
        source.fanart_path = str(fanart)
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def add_source(db: Session, url: str, mode: str = "all") -> MonitoredSource:
    url = url.strip()
    mode = (mode or "all").strip().lower()
    if mode not in VALID_MODES:
        raise ValueError(f"mode must be one of: {', '.join(sorted(VALID_MODES))}")

    url_kind = ytdlp.classify_url(url)
    if mode == "video" and url_kind != "video":
        raise ValueError(
            "“This video only” needs a single video URL (watch?v=… / youtu.be/… / Shorts)."
        )
    if mode in {"new", "all"} and url_kind == "video":
        # Single video link with catalog modes → treat as one-shot video
        mode = "video"

    existing = db.query(MonitoredSource).filter(MonitoredSource.url == url).one_or_none()
    if existing:
        return existing

    info = ytdlp.resolve_source(url)
    source_type = info.source_type
    if mode == "video":
        source_type = "video"

    # Channel URL = uploads tab only (not every playlist on the channel).
    # Playlist URL = that playlist only.
    source = MonitoredSource(
        url=url,
        title=info.title,
        yt_id=info.yt_id,
        source_type=source_type,
        folder_name=info.folder_name,
        enabled=mode != "video",  # one-shot videos don't stay on the monitor loop
        monitor_mode=mode,
        initialized=False,
    )
    db.add(source)
    db.commit()
    db.refresh(source)

    cfg = get_config()
    folder = Path(cfg.library_root) / source.folder_name
    folder.mkdir(parents=True, exist_ok=True)

    if info.thumbnail_url:
        poster = folder / "poster.jpg"
        saved = ytdlp.download_image(info.thumbnail_url, poster)
        if saved:
            source.poster_path = str(saved)
            db.add(source)
            db.commit()
    try:
        ensure_artwork(db, source)
    except Exception:
        db.commit()

    # First sync behavior depends on mode
    check_source(db, source, initial=True, mode=mode)
    downloader.enqueue_wanted(db)
    return source


def check_source(
    db: Session,
    source: MonitoredSource,
    *,
    initial: bool = False,
    mode: str | None = None,
) -> dict:
    entries = ytdlp.list_entries(source.url)
    created_wanted = 0
    created_seen = 0
    # video_id is globally unique — skip ids already owned by any source
    existing_ids = {row[0] for row in db.query(Video.video_id).all()}

    effective_mode = mode or source.monitor_mode or "new"
    is_initial = initial or not source.initialized

    for entry in entries:
        if entry.video_id in existing_ids:
            continue
        if is_initial and effective_mode == "new":
            status = VideoStatus.SEEN.value
        else:
            # "all", "video", or ongoing monitor after init → download
            status = VideoStatus.WANTED.value
        video = Video(
            source_id=source.id,
            video_id=entry.video_id,
            title=entry.title,
            published_at=entry.published_at,
            duration=entry.duration,
            thumbnail_url=entry.thumbnail_url,
            status=status,
        )
        db.add(video)
        existing_ids.add(entry.video_id)
        if status == VideoStatus.WANTED.value:
            created_wanted += 1
        else:
            created_seen += 1

    source.last_checked = datetime.utcnow()
    if is_initial:
        source.initialized = True
    db.add(source)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {
        "source_id": source.id,
        "entries_seen": len(entries),
        "marked_seen": created_seen,
        "marked_wanted": created_wanted,
        "initial": is_initial,
        "mode": effective_mode,
    }


def backfill_source(db: Session, source: MonitoredSource) -> dict:
    """Queue every known SEEN/IGNORED video as wanted, and refresh catalog."""
    # Pick up any videos we haven't listed yet
    result = check_source(db, source, initial=False)
    updated = (
        db.query(Video)
        .filter(
            Video.source_id == source.id,
            Video.status.in_([VideoStatus.SEEN.value, VideoStatus.IGNORED.value]),
        )
        .all()
    )
    for video in updated:
        video.status = VideoStatus.WANTED.value
        video.error = None
        db.add(video)
    source.monitor_mode = "all"
    db.add(source)
    db.commit()
    downloader.enqueue_wanted(db)
    return {
        **result,
        "queued_from_library": len(updated),
    }


def check_all_enabled(db: Session) -> list[dict]:
    results = []
    sources = (
        db.query(MonitoredSource)
        .filter(MonitoredSource.enabled.is_(True))
        .filter(MonitoredSource.monitor_mode != "video")
        .all()
    )
    for source in sources:
        try:
            results.append({"ok": True, **check_source(db, source)})
        except Exception as exc:  # noqa: BLE001
            results.append({"ok": False, "source_id": source.id, "error": str(exc)})
    return results
