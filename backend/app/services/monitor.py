from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import get_config
from ..db import SessionLocal
from ..models import DownloadJob, MonitoredSource, Video, VideoStatus
from . import downloader, ytdlp

# new  = first sync marks existing as seen; later uploads download
# all  = first sync queues entire catalog + keep monitoring new
# none = never auto-queue (catalog stays seen/ignored; episode picks only)
# video = one-shot single video download (no ongoing channel monitor)
VALID_MODES = {"new", "all", "video", "none"}
VALID_MEDIA_TYPES = {"video", "audio"}


def _library_root_for(source: MonitoredSource) -> Path:
    cfg = get_config()
    if (source.media_type or "video").strip().lower() == "audio":
        return Path(cfg.music_library_root)
    return Path(cfg.library_root)


def ensure_artwork(db: Session, source: MonitoredSource) -> MonitoredSource:
    folder = _library_root_for(source) / source.folder_name
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


def cancel_jobs_for_video(db: Session, video: Video, *, reason: str = "Ignored") -> int:
    """Cancel queued/downloading jobs for a video so ignore actually stops the worker."""
    jobs = (
        db.query(DownloadJob)
        .filter(
            DownloadJob.video_id == video.id,
            DownloadJob.status.in_(["queued", "downloading"]),
        )
        .all()
    )
    now = datetime.utcnow()
    for job in jobs:
        job.status = "cancelled"
        job.finished_at = now
        job.error = reason
        db.add(job)
    return len(jobs)


def apply_episode_selection(
    db: Session,
    source: MonitoredSource,
    wanted_video_ids: list[str],
) -> dict:
    """Sonarr-style: only listed episodes stay monitored/wanted; others become ignored."""
    want = {vid.strip() for vid in wanted_video_ids if vid and vid.strip()}
    videos = db.query(Video).filter(Video.source_id == source.id).all()
    wanted_n = 0
    ignored_n = 0
    for video in videos:
        if video.video_id in want:
            if video.status in {
                VideoStatus.SEEN.value,
                VideoStatus.IGNORED.value,
                VideoStatus.FAILED.value,
            }:
                video.status = VideoStatus.WANTED.value
                video.error = None
                db.add(video)
            wanted_n += 1
        else:
            if video.status not in {
                VideoStatus.DOWNLOADED.value,
                VideoStatus.IGNORED.value,
            }:
                video.status = VideoStatus.IGNORED.value
                video.error = "Not selected for download"
                db.add(video)
                cancel_jobs_for_video(db, video, reason="Not selected for download")
                ignored_n += 1
            elif video.status != VideoStatus.DOWNLOADED.value:
                cancel_jobs_for_video(db, video, reason="Not selected for download")
    # Partial picks: do not auto-grab future uploads (episode-level monitor only)
    source.monitor_mode = "none"
    db.add(source)
    db.commit()
    downloader.enqueue_wanted(db)
    return {"wanted": wanted_n, "ignored": ignored_n}


def add_source(
    db: Session,
    url: str,
    mode: str = "all",
    *,
    quality: str = "",
    media_type: str = "video",
    wanted_video_ids: list[str] | None = None,
    title: str | None = None,
    yt_id: str | None = None,
    thumbnail_url: str | None = None,
) -> MonitoredSource:
    """Add a source.

    ``wanted_video_ids``:
      - ``None`` — honor ``mode`` for the whole catalog (Sonarr season monitor).
      - ``list`` — only those episodes become wanted; rest ignored; mode becomes ``none``.
    """
    url = url.strip()
    mode = (mode or "all").strip().lower()
    if mode not in VALID_MODES:
        raise ValueError(f"mode must be one of: {', '.join(sorted(VALID_MODES))}")
    media_type = (media_type or "video").strip().lower()
    if media_type not in VALID_MEDIA_TYPES:
        raise ValueError(f"media_type must be one of: {', '.join(sorted(VALID_MEDIA_TYPES))}")
    quality = (quality or "").strip().lower()
    selective = wanted_video_ids is not None

    url_kind = ytdlp.classify_url(url)
    if mode == "video" and url_kind != "video":
        raise ValueError(
            "“This video only” needs a single video URL (watch?v=… / youtu.be/… / Shorts)."
        )
    if mode in {"new", "all", "none"} and url_kind == "video":
        mode = "video"

    existing = db.query(MonitoredSource).filter(MonitoredSource.url == url).one_or_none()
    if existing:
        if selective:
            # Ensure catalog is listed, then apply episode selection
            check_source(db, existing, initial=False, mode="none")
            apply_episode_selection(db, existing, wanted_video_ids or [])
            db.refresh(existing)
        return existing

    # Prefer search-hit metadata for a fast add (avoids a yt-dlp round-trip)
    hint_title = (title or "").strip()
    if hint_title and url_kind in {"channel", "playlist"}:
        info = ytdlp.SourceInfo(
            title=hint_title,
            yt_id=(yt_id or "").strip() or None,
            source_type=url_kind,
            folder_name=ytdlp._safe_folder_name(hint_title),
            thumbnail_url=(thumbnail_url or "").strip() or None,
            banner_url=None,
            webpage_url=url,
        )
    else:
        info = ytdlp.resolve_source(url)
    source_type = info.source_type
    if mode == "video":
        source_type = "video"

    # Selective episode picks → permanent "none" so monitor loop won't queue the rest
    effective_mode = "none" if selective else mode
    structure_only = effective_mode == "none" and not selective

    source = MonitoredSource(
        url=url,
        title=info.title,
        yt_id=info.yt_id,
        source_type=source_type,
        folder_name=info.folder_name,
        # Structure-only / selective (mode none) and one-shot videos stay unmonitored
        enabled=effective_mode in {"new", "all"},
        monitor_mode=effective_mode,
        quality=quality,
        media_type=media_type,
        initialized=False,
    )
    db.add(source)
    db.commit()
    db.refresh(source)

    folder = _library_root_for(source) / source.folder_name
    folder.mkdir(parents=True, exist_ok=True)

    # Quick poster from known thumb; defer heavy artwork (extra yt-dlp) for structure-only
    if info.thumbnail_url:
        poster = folder / "poster.jpg"
        saved = ytdlp.download_image(info.thumbnail_url, poster)
        if saved:
            source.poster_path = str(saved)
            fanart = folder / "fanart.jpg"
            if not fanart.exists():
                try:
                    import shutil

                    shutil.copy2(saved, fanart)
                    source.fanart_path = str(fanart)
                except OSError:
                    pass
            db.add(source)
            db.commit()

    if not structure_only:
        try:
            ensure_artwork(db, source)
        except Exception:
            db.commit()
    else:
        # Fanart / richer thumbs in the background so Add returns immediately
        source_id = source.id

        def _bg_artwork() -> None:
            s = SessionLocal()
            try:
                row = s.get(MonitoredSource, source_id)
                if row:
                    ensure_artwork(s, row)
            except Exception:
                s.rollback()
            finally:
                s.close()

        import threading

        threading.Thread(target=_bg_artwork, daemon=True).start()

    want_set = (
        {vid.strip() for vid in (wanted_video_ids or []) if vid and vid.strip()}
        if selective
        else None
    )
    # Initial sync: selective path lists everything as ignored except picks
    check_source(
        db,
        source,
        initial=True,
        mode=effective_mode if not selective else "none",
        wanted_ids=want_set,
    )
    downloader.enqueue_wanted(db)
    return source


def check_source(
    db: Session,
    source: MonitoredSource,
    *,
    initial: bool = False,
    mode: str | None = None,
    wanted_ids: set[str] | None = None,
) -> dict:
    effective_mode = mode or source.monitor_mode or "new"
    is_initial = initial or not source.initialized

    # Always enumerate the catalog — including monitor_mode "none" (structure-only /
    # Uploads unchecked). Discovery stays separate from monitoring: videos are stored
    # as SEEN (or IGNORED when wanted_ids is set) and the periodic monitor loop still
    # skips mode "none", so nothing is auto-queued.
    entries = ytdlp.list_entries(source.url)
    created_wanted = 0
    created_seen = 0
    created_ignored = 0
    adopted = 0
    # Per-source uniqueness — same YouTube id may also live under Uploads
    existing_on_source = {
        row[0]
        for row in db.query(Video.video_id).filter(Video.source_id == source.id).all()
    }
    # Adopt file/status from another source when already downloaded
    twins = {
        row.video_id: row
        for row in db.query(Video)
        .filter(
            Video.video_id.in_([e.video_id for e in entries] or ["__none__"]),
            Video.source_id != source.id,
            Video.status == VideoStatus.DOWNLOADED.value,
        )
        .all()
    }

    for entry in entries:
        if entry.video_id in existing_on_source:
            continue
        file_path: str | None = None
        twin = twins.get(entry.video_id)
        if twin and twin.file_path and Path(twin.file_path).exists():
            status = VideoStatus.DOWNLOADED.value
            file_path = twin.file_path
            adopted += 1
        elif wanted_ids is not None:
            if entry.video_id in wanted_ids:
                status = VideoStatus.WANTED.value
            else:
                status = VideoStatus.IGNORED.value
        elif effective_mode == "none":
            status = VideoStatus.SEEN.value
        elif is_initial and effective_mode == "new":
            status = VideoStatus.SEEN.value
        else:
            # "all", "video", or ongoing "new" after init → download new uploads
            status = VideoStatus.WANTED.value
        video = Video(
            source_id=source.id,
            video_id=entry.video_id,
            title=entry.title,
            published_at=entry.published_at,
            duration=entry.duration,
            thumbnail_url=entry.thumbnail_url,
            file_path=file_path,
            status=status,
        )
        db.add(video)
        existing_on_source.add(entry.video_id)
        if status == VideoStatus.WANTED.value:
            created_wanted += 1
        elif status == VideoStatus.IGNORED.value:
            created_ignored += 1
        elif status == VideoStatus.DOWNLOADED.value:
            pass
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
        "marked_ignored": created_ignored,
        "adopted_downloads": adopted,
        "initial": is_initial,
        "mode": effective_mode,
    }


def backfill_source(
    db: Session,
    source: MonitoredSource,
    *,
    include_ignored: bool = False,
) -> dict:
    """Queue SEEN (and optionally IGNORED) videos as wanted, and refresh catalog.

    Ignored episodes stay ignored by default — remonitoring must be explicit
    (include_ignored=True) so Search/Monitor cannot re-flood the queue.
    """
    result = check_source(db, source, initial=False)
    statuses = [VideoStatus.SEEN.value]
    if include_ignored:
        statuses.append(VideoStatus.IGNORED.value)
    updated = (
        db.query(Video)
        .filter(
            Video.source_id == source.id,
            Video.status.in_(statuses),
        )
        .all()
    )
    for video in updated:
        video.status = VideoStatus.WANTED.value
        video.error = None
        db.add(video)
    source.monitor_mode = "all"
    source.enabled = True
    db.add(source)
    db.commit()
    downloader.enqueue_wanted(db)
    return {
        **result,
        "queued_from_library": len(updated),
    }


def delete_source_files(source: MonitoredSource) -> dict:
    """Delete on-disk folder / known file paths for a source (Sonarr-style delete files)."""
    import shutil

    removed: list[str] = []
    errors: list[str] = []
    removed_dirs: list[Path] = []

    cfg = get_config()
    roots = [Path(cfg.library_root), Path(cfg.music_library_root)]
    # Prefer the active media root first
    try:
        primary = _library_root_for(source)
        roots = [primary, *[r for r in roots if r != primary]]
    except Exception:
        pass

    folder_name = (source.folder_name or "").strip()
    if folder_name:
        for root in roots:
            folder = root / folder_name
            if folder.exists() and folder.is_dir():
                try:
                    shutil.rmtree(folder)
                    removed.append(str(folder))
                    removed_dirs.append(folder)
                except OSError as exc:
                    errors.append(f"{folder}: {exc}")

    def _already_gone(path: Path) -> bool:
        try:
            resolved = path.resolve()
        except OSError:
            return False
        for d in removed_dirs:
            try:
                resolved.relative_to(d.resolve())
                return True
            except (ValueError, OSError):
                continue
        return False

    for video in list(source.videos or []):
        if not video.file_path:
            continue
        path = Path(video.file_path)
        if not path.exists() or not path.is_file():
            continue
        if _already_gone(path):
            continue
        try:
            path.unlink()
            removed.append(str(path))
            parent = path.parent
            for root in roots:
                try:
                    if parent.resolve().is_relative_to(root.resolve()) and parent != root.resolve():
                        if parent.exists() and not any(parent.iterdir()):
                            parent.rmdir()
                except (OSError, ValueError):
                    pass
        except OSError as exc:
            errors.append(f"{path}: {exc}")

    return {"removed": removed, "errors": errors}


def check_all_enabled(db: Session) -> list[dict]:
    results = []
    sources = (
        db.query(MonitoredSource)
        .filter(MonitoredSource.enabled.is_(True))
        .filter(MonitoredSource.monitor_mode.notin_(["video", "none"]))
        .all()
    )
    for source in sources:
        try:
            results.append({"ok": True, **check_source(db, source)})
        except Exception as exc:  # noqa: BLE001
            results.append({"ok": False, "source_id": source.id, "error": str(exc)})
    return results
