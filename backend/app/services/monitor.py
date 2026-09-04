from __future__ import annotations

import threading
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


def show_disk_folder(db: Session, source: MonitoredSource) -> str:
    """On-disk show folder: parent channel for nested playlists."""
    if source.parent_source_id and (source.source_type or "").lower() == "playlist":
        parent = db.get(MonitoredSource, source.parent_source_id)
        if parent:
            return (parent.folder_name or parent.title or "Unknown").strip() or "Unknown"
    return (source.folder_name or source.title or "Unknown").strip() or "Unknown"


def ensure_source_season(db: Session, source: MonitoredSource) -> int:
    """Assign Plex season numbers: channel Uploads=1, nested playlists=2+."""
    if (source.media_type or "video").strip().lower() == "audio":
        return int(getattr(source, "season_number", None) or 1)

    st = (source.source_type or "").lower()
    current = int(getattr(source, "season_number", None) or 0)

    if st == "channel":
        if current != 1:
            source.season_number = 1
            db.add(source)
        return 1

    if st == "playlist" and source.parent_source_id:
        if current >= 2:
            return current
        used = {
            int(row[0] or 0)
            for row in db.query(MonitoredSource.season_number)
            .filter(MonitoredSource.parent_source_id == source.parent_source_id)
            .filter(MonitoredSource.id != source.id)
            .all()
        }
        used.add(1)  # reserved for channel Uploads
        n = 2
        while n in used:
            n += 1
        source.season_number = n
        db.add(source)
        return n

    if current < 1:
        source.season_number = 1
        db.add(source)
        return 1
    return current


def refresh_episode_numbers(
    db: Session,
    source: MonitoredSource,
    entries: list | None = None,
) -> None:
    """Set episode_number from playlist_index or uploads chronology (oldest = E01)."""
    if (source.media_type or "video").strip().lower() == "audio":
        return

    videos = db.query(Video).filter(Video.source_id == source.id).all()
    if not videos:
        return

    by_id = {e.video_id: e for e in entries} if entries else {}

    if entries and any(getattr(e, "playlist_index", None) for e in entries):
        for v in videos:
            e = by_id.get(v.video_id)
            if not e:
                continue
            pi = getattr(e, "playlist_index", None)
            if pi is not None:
                try:
                    v.episode_number = int(pi)
                except (TypeError, ValueError):
                    pass
            desc = getattr(e, "description", None)
            if desc and not (v.description or "").strip():
                v.description = str(desc).strip()
            db.add(v)
        return

    # Already numbered (playlist batches) — don't overwrite with date order
    if any(getattr(v, "episode_number", None) for v in videos):
        return

    # Channel Uploads / undated: oldest first → E01
    ordered = sorted(
        videos,
        key=lambda v: (
            v.published_at is None,
            v.published_at or datetime.min,
            v.id,
        ),
    )
    for i, v in enumerate(ordered, start=1):
        if v.episode_number != i:
            v.episode_number = i
            db.add(v)


def ensure_artwork(
    db: Session,
    source: MonitoredSource,
    *,
    force: bool = True,
) -> MonitoredSource:
    folder = _library_root_for(source) / show_disk_folder(db, source)
    # Nested playlists — don't clobber channel poster.jpg
    if source.parent_source_id and (source.source_type or "").lower() == "playlist":
        parent = db.get(MonitoredSource, source.parent_source_id)
        if parent and parent.poster_path and Path(parent.poster_path).is_file() and not force:
            source.poster_path = parent.poster_path
            source.fanart_path = parent.fanart_path or parent.poster_path
            db.add(source)
            db.commit()
            db.refresh(source)
            return source
        folder = folder / "_playlist_art" / ytdlp._safe_folder_name(
            source.yt_id or f"playlist-{source.id}"
        )

    existing_poster = Path(source.poster_path) if source.poster_path else folder / "poster.jpg"
    if not force and ytdlp.image_file_ok(existing_poster):
        if not source.poster_path:
            source.poster_path = str(existing_poster)
            db.add(source)
            db.commit()
            db.refresh(source)
        return source

    folder.mkdir(parents=True, exist_ok=True)
    poster, fanart = ytdlp.fetch_channel_artwork(source.url, folder)

    # Fall back to a catalog video thumb when channel avatar download fails
    if not poster:
        videos = (
            db.query(Video)
            .filter(Video.source_id == source.id)
            .order_by(Video.published_at.desc(), Video.id.desc())
            .limit(3)
            .all()
        )
        poster_file = folder / "poster.jpg"
        for video in videos:
            candidates: list[str] = []
            if video.thumbnail_url:
                candidates.append(video.thumbnail_url)
            vid = (video.video_id or "").strip()
            if vid:
                candidates.append(f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg")
                candidates.append(f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg")
            for cand in candidates:
                saved = ytdlp.download_image(cand, poster_file)
                if saved:
                    poster = saved
                    break
            if poster:
                break

    if poster and ytdlp.image_file_ok(poster):
        source.poster_path = str(poster)
    else:
        keep: Path | None = None
        for candidate in (
            folder / "poster.jpg",
            Path(source.poster_path) if source.poster_path else None,
        ):
            if candidate and ytdlp.image_file_ok(candidate):
                keep = candidate
                break
            if candidate and candidate.is_file():
                try:
                    candidate.unlink(missing_ok=True)
                except OSError:
                    pass
        if keep:
            source.poster_path = str(keep)
            poster = keep
        else:
            source.poster_path = None
            poster = None

    if fanart:
        source.fanart_path = str(fanart)
    elif poster and poster.is_file():
        fanart_file = folder / "fanart.jpg"
        if not fanart_file.exists():
            try:
                import shutil

                shutil.copy2(poster, fanart_file)
                source.fanart_path = str(fanart_file)
            except OSError:
                pass

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
    kill_ids: list[int] = []
    for job in jobs:
        if job.status == "downloading":
            kill_ids.append(job.id)
        job.status = "cancelled"
        job.finished_at = now
        job.error = reason
        db.add(job)
    for jid in kill_ids:
        try:
            downloader.cancel_job_process(jid)
        except Exception:
            pass
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


def refresh_source_metadata(db: Session, source: MonitoredSource) -> bool:
    """Pull the YouTube About text / subscriber count for an existing source.

    Sources added before this existed (or added from a search hit, which carries no
    About text) have description NULL — this backfills them on demand.
    """
    info = ytdlp.resolve_source(source.url)
    changed = False
    # "" marks "asked YouTube, nothing there" so we stop re-fetching every visit.
    new_desc = info.description if info.description is not None else ""
    if (source.description or None) != (new_desc or None) or source.description is None:
        source.description = new_desc
        changed = True
    if info.subscriber_count is not None and source.subscriber_count != info.subscriber_count:
        source.subscriber_count = info.subscriber_count
        changed = True
    if changed:
        db.add(source)
        db.commit()
        db.refresh(source)
    return changed


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
    channel: str | None = None,
    parent_source_id: int | None = None,
) -> MonitoredSource:
    """Add a source.

    ``wanted_video_ids``:
      - ``None`` — honor ``mode`` for the whole catalog (Sonarr season monitor).
      - ``list`` — only those episodes become wanted; rest ignored; mode becomes ``none``.

    ``parent_source_id``:
      Nest a playlist under a channel so the library shows one poster for the channel.
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

    parent_id: int | None = None
    if parent_source_id is not None:
        parent = db.get(MonitoredSource, int(parent_source_id))
        if not parent:
            raise ValueError("parent_source_id does not exist")
        if parent.source_type != "channel":
            raise ValueError("parent_source_id must be a channel")
        parent_id = parent.id

    url_kind = ytdlp.classify_url(url)
    if mode == "video" and url_kind != "video":
        raise ValueError(
            "“This video only” needs a single video URL (watch?v=… / youtu.be/… / Shorts)."
        )
    if mode in {"new", "all", "none"} and url_kind == "video":
        mode = "video"
    if parent_id is not None and url_kind != "playlist":
        raise ValueError("Only playlists can nest under a channel parent")

    existing = db.query(MonitoredSource).filter(MonitoredSource.url == url).one_or_none()
    if existing:
        changed = False
        if parent_id is not None and getattr(existing, "parent_source_id", None) != parent_id:
            existing.parent_source_id = parent_id
            changed = True
        # Re-add with new options should update the existing row (not silently no-op)
        if not selective:
            if quality and (existing.quality or "") != quality:
                existing.quality = quality
                changed = True
            if media_type and (existing.media_type or "video") != media_type:
                existing.media_type = media_type
                changed = True
            if mode and mode != "video" and (existing.monitor_mode or "") != mode:
                # Don't convert one-shot videos into channel monitors via URL re-add
                if existing.monitor_mode != "video":
                    existing.monitor_mode = mode
                    existing.enabled = mode in {"new", "all"}
                    changed = True
            if title and (title or "").strip() and existing.title != title.strip():
                existing.title = title.strip()
                changed = True
        if changed:
            ensure_source_season(db, existing)
        if selective:
            source_id = existing.id
            picks = list(wanted_video_ids or [])

            def _bg_selective() -> None:
                s = SessionLocal()
                try:
                    row = s.get(MonitoredSource, source_id)
                    if not row:
                        return
                    check_source(s, row, initial=False, mode="none")
                    apply_episode_selection(s, row, picks)
                    downloader.enqueue_wanted(s)
                except Exception:
                    s.rollback()
                finally:
                    s.close()

            threading.Thread(target=_bg_selective, daemon=True).start()
        if changed:
            db.add(existing)
            db.commit()
            db.refresh(existing)
        return existing

    # Prefer search-hit metadata for a fast add (avoids a yt-dlp round-trip)
    hint_title = (title or "").strip()
    hint_channel = (channel or "").strip()
    if hint_title and url_kind in {"channel", "playlist", "video"}:
        if url_kind == "video":
            # Single track/video: folder = artist/channel (Plex Music / channel folder)
            folder_base = hint_channel or (
                "Unknown Artist" if media_type == "audio" else "YouTube Videos"
            )
        else:
            folder_base = hint_title
        info = ytdlp.SourceInfo(
            title=hint_title,
            yt_id=(yt_id or "").strip() or None,
            source_type=url_kind,
            folder_name=ytdlp._safe_folder_name(folder_base),
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
        parent_source_id=parent_id if source_type == "playlist" else None,
        season_number=1,
        initialized=False,
        description=info.description,
        subscriber_count=info.subscriber_count,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    ensure_source_season(db, source)
    db.commit()
    db.refresh(source)

    show_folder = show_disk_folder(db, source)
    folder = _library_root_for(source) / show_folder
    folder.mkdir(parents=True, exist_ok=True)
    if (media_type or "video") != "audio":
        season = int(getattr(source, "season_number", None) or 1)
        (folder / f"Season {season:02d}").mkdir(parents=True, exist_ok=True)

    # Quick poster from known thumb so the UI has art immediately
    # Nested playlists must not overwrite the channel poster.jpg
    if info.thumbnail_url and not (
        parent_id and source_type == "playlist"
    ):
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

    # Catalog sync + artwork + enqueue are slow (yt-dlp). Never block Add / navigation.
    source_id = source.id
    want_set = (
        {vid.strip() for vid in (wanted_video_ids or []) if vid and vid.strip()}
        if selective
        else None
    )
    sync_mode = effective_mode if not selective else "none"
    # Always try artwork — library posters matter even for structure-only channels
    do_artwork = True

    def _bg_initial_sync() -> None:
        s = SessionLocal()
        try:
            row = s.get(MonitoredSource, source_id)
            if not row:
                return
            if do_artwork:
                try:
                    ensure_artwork(s, row)
                except Exception:
                    s.rollback()
                    row = s.get(MonitoredSource, source_id)
                    if not row:
                        return
            check_source(
                s,
                row,
                initial=True,
                mode=sync_mode,
                wanted_ids=want_set,
            )
            downloader.enqueue_wanted(s)
        except Exception as exc:
            s.rollback()
            try:
                from . import applog

                applog.log_error(
                    f"Initial catalog sync failed for source id={source_id}: {exc}",
                    source="monitor",
                )
            except Exception:
                pass
        finally:
            s.close()

    threading.Thread(target=_bg_initial_sync, name=f"ytarr-add-{source_id}", daemon=True).start()
    return source


_CATALOG_BATCH = 200


def _ingest_new_entries(
    db: Session,
    source: MonitoredSource,
    entries: list,
    existing_on_source: set[str],
    *,
    wanted_ids: set[str] | None,
    effective_mode: str,
    is_initial: bool,
) -> tuple[int, int, int, int]:
    """Insert catalog rows that this source does not already have. Returns counts."""
    created_wanted = created_seen = created_ignored = adopted = 0
    if not entries:
        return created_wanted, created_seen, created_ignored, adopted
    twins = {
        row.video_id: row
        for row in db.query(Video)
        .filter(
            Video.video_id.in_([e.video_id for e in entries]),
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
            status = (
                VideoStatus.WANTED.value
                if entry.video_id in wanted_ids
                else VideoStatus.IGNORED.value
            )
        elif effective_mode == "none":
            status = VideoStatus.SEEN.value
        elif is_initial and effective_mode == "new":
            status = VideoStatus.SEEN.value
        else:
            status = VideoStatus.WANTED.value
        video = Video(
            source_id=source.id,
            video_id=entry.video_id,
            title=entry.title,
            published_at=entry.published_at,
            duration=entry.duration,
            thumbnail_url=entry.thumbnail_url,
            description=getattr(entry, "description", None),
            episode_number=getattr(entry, "playlist_index", None),
            file_path=file_path,
            status=status,
        )
        db.add(video)
        existing_on_source.add(entry.video_id)
        if status == VideoStatus.WANTED.value:
            created_wanted += 1
        elif status == VideoStatus.IGNORED.value:
            created_ignored += 1
        elif status != VideoStatus.DOWNLOADED.value:
            created_seen += 1
    return created_wanted, created_seen, created_ignored, adopted


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
    # Bounded poll for mode=new after initial sync — full dump only on first sync / all / none.
    list_limit: int | None = None
    if not is_initial and effective_mode == "new":
        list_limit = 40
    ensure_source_season(db, source)
    created_wanted = created_seen = created_ignored = adopted = 0
    existing_on_source = {
        row[0]
        for row in db.query(Video.video_id).filter(Video.source_id == source.id).all()
    }
    entries_seen = 0
    last_batch: list = []

    def _apply(batch: list) -> None:
        nonlocal created_wanted, created_seen, created_ignored, adopted, entries_seen, last_batch
        last_batch = batch
        entries_seen += len(batch)
        w, s, i, a = _ingest_new_entries(
            db,
            source,
            batch,
            existing_on_source,
            wanted_ids=wanted_ids,
            effective_mode=effective_mode,
            is_initial=is_initial,
        )
        created_wanted += w
        created_seen += s
        created_ignored += i
        adopted += a

    if list_limit is not None:
        _apply(ytdlp.list_entries(source.url, limit=list_limit))
        refresh_episode_numbers(db, source, last_batch)
    else:
        start = 1
        while True:
            end = start + _CATALOG_BATCH - 1
            batch = ytdlp.list_entries(
                source.url,
                playlist_start=start,
                playlist_end=end,
            )
            if not batch:
                break
            _apply(batch)
            db.commit()
            if len(batch) < _CATALOG_BATCH:
                break
            start += _CATALOG_BATCH
        refresh_episode_numbers(db, source, last_batch if any(
            getattr(e, "playlist_index", None) for e in last_batch
        ) else None)

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
        "entries_seen": entries_seen,
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


def delete_source_files(source: MonitoredSource, db: Session | None = None) -> dict:
    """Delete on-disk folder / known file paths for a source (Sonarr-style delete files).

    Nested playlist seasons live under the parent channel folder
    (``Channel/Season XX``) — never delete a sibling-named folder at library root.
    """
    import shutil

    from sqlalchemy.orm import object_session

    from . import rename

    removed: list[str] = []
    errors: list[str] = []
    removed_dirs: list[Path] = []

    cfg = get_config()
    roots = [Path(cfg.library_root), Path(cfg.music_library_root)]
    try:
        primary = _library_root_for(source)
        roots = [primary, *[r for r in roots if r != primary]]
    except Exception:
        pass

    sess = db or object_session(source)
    parent_id = getattr(source, "parent_source_id", None)
    is_nested_playlist = (
        (source.source_type or "") == "playlist" and parent_id is not None
    )

    targets: list[Path] = []
    if is_nested_playlist:
        show = show_disk_folder(sess, source) if sess else (
            (source.folder_name or source.title or "Unknown").strip() or "Unknown"
        )
        season = int(getattr(source, "season_number", None) or 1)
        season = max(1, min(season, 999))
        for root in roots:
            targets.append(root / show / f"Season {season:02d}")
            # Playlist art lives beside seasons, not inside them
            art = root / show / "_playlist_art" / rename._safe_name(
                source.folder_name or source.title or "playlist"
            )
            targets.append(art)
    else:
        show = show_disk_folder(sess, source) if sess else (
            (source.folder_name or source.title or "Unknown").strip() or "Unknown"
        )
        for root in roots:
            targets.append(root / show)
            folder_name = (source.folder_name or "").strip()
            if folder_name and folder_name != show:
                targets.append(root / folder_name)

    seen: set[str] = set()
    for folder in targets:
        key = str(folder).lower()
        if key in seen:
            continue
        seen.add(key)
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


def _playlist_list_id(url: str) -> str | None:
    from urllib.parse import parse_qs, urlparse

    try:
        q = parse_qs(urlparse(url).query)
        vals = q.get("list") or []
        return vals[0] if vals else None
    except Exception:
        return None


def child_playlist_sources(db: Session, channel_id: int) -> list[MonitoredSource]:
    return (
        db.query(MonitoredSource)
        .filter(MonitoredSource.parent_source_id == channel_id)
        .filter(MonitoredSource.source_type == "playlist")
        .all()
    )


def delete_source_tree(
    db: Session,
    source: MonitoredSource,
    *,
    delete_files: bool = False,
) -> dict:
    """Delete a source and nested playlist seasons (channel delete)."""
    removed: list[str] = []
    errors: list[str] = []
    children: list[MonitoredSource] = []
    if source.source_type == "channel":
        children = child_playlist_sources(db, source.id)

    for child in children:
        if delete_files:
            _ = list(child.videos)
            fr = delete_source_files(child, db)
            removed.extend(fr.get("removed") or [])
            errors.extend(fr.get("errors") or [])
        db.delete(child)

    if delete_files:
        _ = list(source.videos)
        fr = delete_source_files(source, db)
        removed.extend(fr.get("removed") or [])
        errors.extend(fr.get("errors") or [])

    db.delete(source)
    db.commit()
    return {
        "removed": removed,
        "errors": errors,
        "nested_deleted": len(children),
    }


def link_orphan_playlists_fast(db: Session) -> int:
    """Nest orphan playlists under channels without network calls.

    Covers the common case where a playlist was added alongside its channel and
    shares the channel title (looks like a duplicate library poster).
    """
    orphans = (
        db.query(MonitoredSource)
        .filter(MonitoredSource.source_type == "playlist")
        .filter(MonitoredSource.parent_source_id.is_(None))
        .all()
    )
    if not orphans:
        return 0

    channels = (
        db.query(MonitoredSource).filter(MonitoredSource.source_type == "channel").all()
    )
    if not channels:
        return 0

    by_title: dict[str, list[MonitoredSource]] = {}
    by_yt: dict[str, MonitoredSource] = {}
    for ch in channels:
        key = (ch.title or "").strip().lower()
        if key:
            by_title.setdefault(key, []).append(ch)
        yid = (ch.yt_id or "").strip()
        if yid:
            by_yt[yid] = ch

    linked = 0
    for pl in orphans:
        parent: MonitoredSource | None = None
        title_key = (pl.title or "").strip().lower()
        title_hits = by_title.get(title_key) or []
        if len(title_hits) == 1 and _playlist_list_id(pl.url or ""):
            # Title match alone is too loose when many channels exist — require a
            # playlist list= id in the URL so we don't nest under the wrong channel.
            parent = title_hits[0]
        else:
            # Older adds sometimes stored the channel UC… id on the playlist row
            yid = (pl.yt_id or "").strip()
            if yid and yid in by_yt and _playlist_list_id(pl.url or ""):
                parent = by_yt[yid]
        if parent is None:
            continue
        pl.parent_source_id = parent.id
        # Prefer real playlist id from the URL when yt_id was wrongly the channel id
        list_id = _playlist_list_id(pl.url or "")
        if list_id and (not pl.yt_id or pl.yt_id in by_yt):
            pl.yt_id = list_id
        db.add(pl)
        linked += 1

    if linked:
        db.commit()
    return linked


def link_orphan_playlists(
    db: Session,
    *,
    scrape: bool = True,
    max_channels: int | None = None,
    skip_fast: bool = False,
) -> int:
    """Attach standalone playlist sources to their parent channel when possible.

    Fast title/id heuristics first, then (optionally) each channel's live YouTube
    /playlists tab. ``max_channels`` caps how many channels are scraped.
    """
    linked = 0 if skip_fast else link_orphan_playlists_fast(db)
    if not scrape:
        return linked

    orphans = (
        db.query(MonitoredSource)
        .filter(MonitoredSource.source_type == "playlist")
        .filter(MonitoredSource.parent_source_id.is_(None))
        .all()
    )
    if not orphans:
        return linked

    channels = (
        db.query(MonitoredSource).filter(MonitoredSource.source_type == "channel").all()
    )
    if not channels:
        return linked
    if max_channels is not None:
        channels = channels[: max(0, int(max_channels))]

    for ch in channels:
        try:
            hits = ytdlp.list_channel_playlists(ch.url, limit=100)
        except Exception:
            continue
        hit_ids: set[str] = set()
        hit_titles: set[str] = set()
        for h in hits:
            if h.id:
                hit_ids.add(h.id)
            lid = _playlist_list_id(h.url or "")
            if lid:
                hit_ids.add(lid)
            if h.title:
                hit_titles.add(h.title.strip().lower())
        if not hit_ids and not hit_titles:
            continue
        for pl in orphans:
            if pl.parent_source_id is not None:
                continue
            pl_id = (pl.yt_id or "").strip() or _playlist_list_id(pl.url or "")
            title_key = (pl.title or "").strip().lower()
            id_match = bool(pl_id) and (
                pl_id in hit_ids
                or any(pl_id.startswith(hid) or hid.startswith(pl_id) for hid in hit_ids)
            )
            title_match = bool(title_key) and title_key in hit_titles
            if id_match or title_match:
                pl.parent_source_id = ch.id
                if pl_id and (not pl.yt_id or str(pl.yt_id).startswith("UC")):
                    lid = _playlist_list_id(pl.url or "") or (pl_id if not pl_id.startswith("UC") else None)
                    if lid:
                        pl.yt_id = lid
                db.add(pl)
                linked += 1
    if linked:
        db.commit()
    return linked


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
