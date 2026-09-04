from __future__ import annotations

import shutil
import threading
from datetime import datetime
from pathlib import Path

from sqlalchemy import exists
from sqlalchemy.orm import Session

from ..config import get_config, set_config
from ..db import SessionLocal
from ..models import DownloadJob, MonitoredSource, Video, VideoStatus
from . import quality, ytdlp


_lock = threading.RLock()
_active = 0

# Refuse to start a download if free space is below this (bytes)
MIN_FREE_BYTES = 500 * 1024 * 1024


def _find_downloaded_file(
    video_id: str,
    *,
    prefer_dirs: list[Path] | None = None,
) -> Path | None:
    """Look for a completed file under the show folder only — never the whole library."""
    needles = (f"[{video_id}]", f"({video_id})")

    def _scan(root: Path, *, recursive: bool) -> Path | None:
        if not root.exists():
            return None
        try:
            iterator = root.rglob("*") if recursive else root.iterdir()
            for path in iterator:
                if path.is_file() and any(n in path.name for n in needles):
                    return path
        except OSError:
            return None
        return None

    seen: set[Path] = set()
    for root in prefer_dirs or []:
        key = root.resolve() if root.exists() else root
        if key in seen:
            continue
        seen.add(key)
        hit = _scan(root, recursive=False) or _scan(root, recursive=True)
        if hit:
            return hit
    return None


def recover_interrupted_downloads() -> dict:
    """After a restart, finish or re-queue jobs left stuck in 'downloading'."""
    db = SessionLocal()
    fixed = 0
    requeued = 0
    try:
        jobs = (
            db.query(DownloadJob)
            .filter(DownloadJob.status == "downloading")
            .order_by(DownloadJob.id.asc())
            .all()
        )
        for job in jobs:
            video = db.get(Video, job.video_id)
            if not video:
                job.status = "failed"
                job.error = "Video missing after restart"
                job.finished_at = datetime.utcnow()
                db.add(job)
                fixed += 1
                continue
            existing = None
            if video.file_path and Path(video.file_path).exists():
                existing = Path(video.file_path)
            if existing is None:
                prefer: list[Path] = []
                source = video.source or db.get(MonitoredSource, video.source_id)
                if source:
                    from . import rename

                    root = (
                        Path(get_config().music_library_root)
                        if (source.media_type or "video").strip().lower() == "audio"
                        else Path(get_config().library_root)
                    )
                    show = rename.show_folder_name(source)
                    prefer.append(root / show)
                    season = rename.season_number_for(source)
                    prefer.append(root / show / f"Season {season:02d}")
                    folder = (source.folder_name or "").strip()
                    if folder and folder != show:
                        prefer.append(root / folder)
                existing = _find_downloaded_file(video.video_id, prefer_dirs=prefer)
            if existing is not None:
                video.status = VideoStatus.DOWNLOADED.value
                video.file_path = str(existing)
                video.error = None
                job.status = "completed"
                job.progress = 100.0
                job.finished_at = job.finished_at or datetime.utcnow()
                job.error = None
                db.add(video)
                db.add(job)
                fixed += 1
            else:
                video.status = VideoStatus.QUEUED.value
                video.error = None
                job.status = "queued"
                job.progress = 0.0
                job.started_at = None
                job.error = "Re-queued after app restart"
                db.add(video)
                db.add(job)
                requeued += 1
        if fixed or requeued:
            db.commit()
        return {"completed": fixed, "requeued": requeued}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def enqueue_wanted(db: Session, limit: int = 500) -> int:
    """Queue wanted videos that do not already have an active download job."""
    cfg = get_config()
    if cfg.downloads_paused:
        return 0
    cap = max(1, min(int(limit), 2000))
    with _lock:
        has_active_job = exists().where(
            DownloadJob.video_id == Video.id,
            DownloadJob.status.in_(["queued", "downloading"]),
        )
        videos = (
            db.query(Video)
            .filter(Video.status == VideoStatus.WANTED.value)
            .filter(~has_active_job)
            .order_by(Video.published_at.asc(), Video.id.asc())
            .limit(cap)
            .all()
        )
        count = 0
        for video in videos:
            video.status = VideoStatus.QUEUED.value
            job = DownloadJob(video_id=video.id, status="queued", progress=0.0)
            db.add(video)
            db.add(job)
            count += 1
        if count:
            db.commit()
        return count


_progress_last: dict[int, tuple[float, float]] = {}  # job_id -> (monotonic_ts, pct)


def _set_progress(db: Session, job_id: int, pct: float) -> None:
    """Throttle SQLite commits — yt-dlp emits many % lines per second."""
    import time

    pct = max(0.0, min(100.0, pct))
    now = time.monotonic()
    prev = _progress_last.get(job_id)
    if prev is not None:
        last_ts, last_pct = prev
        if pct < 100.0 and (now - last_ts) < 1.0 and abs(pct - last_pct) < 2.0:
            return
    _progress_last[job_id] = (now, pct)
    job = db.get(DownloadJob, job_id)
    if not job:
        return
    job.progress = pct
    db.add(job)
    db.commit()
    if pct >= 100.0:
        _progress_last.pop(job_id, None)


def _is_disk_full_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    needles = (
        "no space left",
        "not enough space",
        "disk full",
        "errno 28",
        "os error 112",  # Windows ERROR_DISK_FULL
        "there is not enough space",
    )
    return any(n in msg for n in needles)


def _is_permanent_download_error(msg: str) -> bool:
    """True for removals/private — do not auto-retry."""
    err_l = msg.lower()
    permanent = (
        "private video",
        "has been removed",
        "account associated with this video has been terminated",
        "login required",
        "sign in if you've been granted access",
        "members-only",
        "members only",
        "join this channel",
    )
    if any(s in err_l for s in permanent):
        return True
    # "unavailable" alone is ambiguous (can be bot-check); only permanent when clearly removed
    if "video unavailable" in err_l and any(
        s in err_l for s in ("removed", "deleted", "terminated", "private")
    ):
        return True
    return False


def _is_auth_block_error(msg: str) -> bool:
    err_l = msg.lower()
    return any(
        s in err_l
        for s in (
            "http error 403",
            "403 forbidden",
            "sign in to confirm",
            "confirm you're not a bot",
            "confirm you are not a bot",
            "cookies",
            "bot check",
            "dpapi",
            "app-bound",
            "app_bound",
        )
    )


# Backoff minutes by retry_count after a transient failure (before next auto requeue)
_RETRY_BACKOFF_MINUTES = (15, 60, 360)
_MAX_AUTO_RETRIES = 3


def requeue_retryable_failures(db: Session) -> int:
    """Promote aged transient FAILED videos back to WANTED (capped attempts)."""
    now = datetime.utcnow()
    failed = (
        db.query(Video)
        .filter(Video.status == VideoStatus.FAILED.value)
        .order_by(Video.updated_at.asc())
        .limit(50)
        .all()
    )
    n = 0
    for video in failed:
        if _is_permanent_download_error(video.error or ""):
            continue
        if _is_auth_block_error(video.error or ""):
            # Stay failed until user sets cookies and clicks Retry
            continue
        count = int(getattr(video, "retry_count", 0) or 0)
        if count >= _MAX_AUTO_RETRIES:
            continue
        wait_m = _RETRY_BACKOFF_MINUTES[min(count, len(_RETRY_BACKOFF_MINUTES) - 1)]
        updated = video.updated_at or video.created_at or now
        age_m = (now - updated).total_seconds() / 60.0
        if age_m < wait_m:
            continue
        video.status = VideoStatus.WANTED.value
        video.error = None
        video.retry_count = count + 1
        db.add(video)
        n += 1
    if n:
        db.commit()
    return n


def _pause_downloads(reason: str) -> None:
    cfg = get_config()
    if cfg.downloads_paused:
        return
    cfg.downloads_paused = True
    set_config(cfg)
    # Best-effort: surface reason on the next failed job; Activity shows paused flag


def _free_bytes(path: Path) -> int | None:
    try:
        path.mkdir(parents=True, exist_ok=True)
        return shutil.disk_usage(path).free
    except OSError:
        return None


def cancel_job_process(job_id: int) -> bool:
    """Kill the yt-dlp process tree for a downloading job (if any)."""
    return ytdlp.kill_download_process(job_id)


def cancel_all_queued(db: Session) -> int:
    """Cancel every queued/downloading job and mark those videos ignored (panic stop)."""
    jobs = (
        db.query(DownloadJob)
        .filter(DownloadJob.status.in_(["queued", "downloading"]))
        .all()
    )
    now = datetime.utcnow()
    n = 0
    downloading_ids: list[int] = []
    for job in jobs:
        if job.status == "downloading":
            downloading_ids.append(job.id)
        job.status = "cancelled"
        job.finished_at = now
        job.error = "Cancelled (queue cleared)"
        db.add(job)
        video = db.get(Video, job.video_id)
        if video and video.status in {
            VideoStatus.QUEUED.value,
            VideoStatus.WANTED.value,
            VideoStatus.DOWNLOADING.value,
        }:
            video.status = VideoStatus.IGNORED.value
            video.error = job.error
            db.add(video)
        n += 1
    # Also clear wanted that never got a job yet
    wanted = db.query(Video).filter(Video.status == VideoStatus.WANTED.value).all()
    for video in wanted:
        video.status = VideoStatus.IGNORED.value
        video.error = "Cancelled (queue cleared)"
        db.add(video)
        n += 1
    db.commit()
    for jid in downloading_ids:
        ytdlp.kill_download_process(jid)
    return n


def process_next_download() -> bool:
    """Pick one queued video and download it. Returns True if work was done."""
    global _active
    cfg = get_config()
    if cfg.downloads_paused:
        return False

    db = SessionLocal()
    job: DownloadJob | None = None
    video: Video | None = None
    claimed = False
    try:
        with _lock:
            if _active >= max(1, cfg.concurrent_downloads):
                return False
            job = (
                db.query(DownloadJob)
                .filter(DownloadJob.status == "queued")
                .order_by(DownloadJob.id.asc())
                .first()
            )
            if not job:
                enqueue_wanted(db)
                job = (
                    db.query(DownloadJob)
                    .filter(DownloadJob.status == "queued")
                    .order_by(DownloadJob.id.asc())
                    .first()
                )
            if not job:
                return False

            video = db.get(Video, job.video_id)
            if not video:
                job.status = "failed"
                job.error = "Video missing"
                job.finished_at = datetime.utcnow()
                db.add(job)
                db.commit()
                return True

            # Selection/ignore must win — never start (or restart) ignored items
            if video.status == VideoStatus.IGNORED.value:
                job.status = "cancelled"
                job.finished_at = datetime.utcnow()
                job.error = "Ignored — not selected for download"
                db.add(job)
                db.commit()
                return True

            job.status = "downloading"
            job.started_at = datetime.utcnow()
            job.progress = 0.0
            video.status = VideoStatus.DOWNLOADING.value
            video.error = None
            db.add(job)
            db.add(video)
            db.commit()
            _active += 1
            claimed = True

        source = db.get(MonitoredSource, video.source_id)
        media_type = (source.media_type if source else "video") or "video"
        extract_audio = media_type.strip().lower() == "audio"
        if extract_audio:
            library_root = Path(cfg.music_library_root)
            output_template = cfg.music_output_template or cfg.output_template
        else:
            library_root = Path(cfg.library_root)
            output_template = cfg.output_template

        # Same YouTube id already downloaded under another season — copy into this
        # show folder so delete-files on one source cannot orphan the other.
        twin = (
            db.query(Video)
            .filter(
                Video.video_id == video.video_id,
                Video.id != video.id,
                Video.status == VideoStatus.DOWNLOADED.value,
                Video.file_path.isnot(None),
            )
            .first()
        )
        if twin and twin.file_path and Path(twin.file_path).exists():
            import shutil

            from . import rename

            twin_path = Path(twin.file_path)
            dest = twin_path
            try:
                # Copy first so organize never moves the twin's only file
                tmp = twin_path.parent / f".ytarr-twin-{video.video_id}{twin_path.suffix}"
                shutil.copy2(twin_path, tmp)
                dest = rename.organize_downloaded_file(db, video, source, tmp)
                if dest.exists() and tmp.exists() and dest.resolve() != tmp.resolve():
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
            except Exception:
                dest = twin_path
            job.status = "completed"
            job.progress = 100.0
            job.finished_at = datetime.utcnow()
            job.error = None
            video.status = VideoStatus.DOWNLOADED.value
            video.file_path = str(dest)
            video.error = None
            db.add(job)
            db.add(video)
            db.commit()
            return True

        free = _free_bytes(library_root)
        if free is not None and free < MIN_FREE_BYTES:
            _pause_downloads("disk space low")
            job.status = "failed"
            job.error = (
                f"Paused: less than 500 MB free on {library_root} "
                f"({free // (1024 * 1024)} MB free). Free space, then resume in Activity."
            )
            job.finished_at = datetime.utcnow()
            video.status = VideoStatus.FAILED.value
            video.error = job.error
            db.add(job)
            db.add(video)
            db.commit()
            return True

        job_id = job.id
        video_id = video.video_id
        source_id = video.source_id
        music_default = getattr(cfg, "default_music_quality", None) or "best"
        music_fmt = getattr(cfg, "music_format", None) or "ba/b"
        src_quality = source.quality if source else ""
        media_type_snap = media_type
        extract_audio_snap = extract_audio
        library_root_snap = library_root
        output_template_snap = output_template
        fmt = quality.resolve_format_selector(
            src_quality,
            default_quality=cfg.default_quality,
            custom_format=music_fmt if extract_audio else cfg.format,
            media_type=media_type,
            default_music_quality=music_default,
        )
        audio_q = (
            quality.resolve_audio_ffmpeg_quality(src_quality, default_quality=music_default)
            if extract_audio
            else "0"
        )

        sb_cats: str | None = None
        if getattr(cfg, "sponsorblock_remove", True):
            if extract_audio:
                sb_cats = getattr(cfg, "sponsorblock_categories_music", None) or (
                    "music_offtopic,sponsor,selfpromo,interaction,intro,outro"
                )
            else:
                sb_cats = getattr(cfg, "sponsorblock_categories_video", None) or (
                    "sponsor,selfpromo,interaction,intro,outro"
                )

        # Release the DB connection for the long yt-dlp run
        db.close()
        db = None  # type: ignore[assignment]

        def on_progress(pct: float) -> None:
            s = SessionLocal()
            try:
                _set_progress(s, job_id, pct)
            finally:
                s.close()

        file_path = ytdlp.download_video(
            ytdlp.video_page_url(video_id),
            library_root=library_root_snap,
            output_template=output_template_snap,
            format_selector=fmt,
            progress_cb=on_progress,
            extract_audio=extract_audio_snap,
            audio_quality=audio_q,
            sponsorblock_categories=sb_cats,
            job_id=job_id,
        )

        db = SessionLocal()
        job = db.get(DownloadJob, job_id)
        video = db.get(Video, job.video_id) if job else None
        source = db.get(MonitoredSource, source_id) if video else None
        extract_audio = extract_audio_snap
        library_root = library_root_snap

        # refresh — honor cancel/ignore that happened during download
        if job and video:
            if job.status == "cancelled" or video.status == VideoStatus.IGNORED.value:
                job.status = "cancelled"
                job.finished_at = job.finished_at or datetime.utcnow()
                job.error = job.error or "Cancelled"
                video.status = VideoStatus.IGNORED.value
                if file_path:
                    video.file_path = str(file_path)
                db.add(job)
                db.add(video)
                db.commit()
                return True
            # yt-dlp can exit 0 without printing a filepath — recover or fail cleanly
            resolved: Path | None = Path(file_path) if file_path else None
            if resolved is None or not resolved.exists():
                prefer: list[Path] = []
                if source:
                    from . import rename

                    show = rename.show_folder_name(source)
                    prefer.append(library_root / show)
                    prefer.append(
                        library_root / show / f"Season {rename.season_number_for(source):02d}"
                    )
                    folder = (source.folder_name or "").strip()
                    if folder and folder != show:
                        prefer.append(library_root / folder)
                resolved = _find_downloaded_file(video_id, prefer_dirs=prefer)
            if resolved is None or not resolved.exists():
                job.status = "failed"
                job.finished_at = datetime.utcnow()
                job.error = "Download finished but no media file was found on disk"
                video.status = VideoStatus.FAILED.value
                video.error = job.error
                db.add(job)
                db.add(video)
                db.commit()
                return True

            job.status = "completed"
            job.progress = 100.0
            job.finished_at = datetime.utcnow()
            video.status = VideoStatus.DOWNLOADED.value
            video.error = None
            video.retry_count = 0
            from . import musicbrainz, rename

            organized = rename.organize_downloaded_file(db, video, source, resolved)
            video.file_path = str(organized)
            if extract_audio and organized.exists():
                artist = rename.music_artist_folder(source, video, organized)
                try:
                    musicbrainz.enrich_music_file(
                        organized,
                        title=video.title or organized.stem,
                        artist=artist,
                        youtube_id=video.video_id,
                    )
                except Exception:
                    pass
            elif not extract_audio and organized.exists() and not (video.description or "").strip():
                try:
                    from . import ytdlp as ytdlp_svc

                    desc = ytdlp_svc.fetch_video_description(video.video_id)
                    if desc:
                        video.description = desc
                        from . import nfo

                        nfo.write_video_nfo(organized, video, source, description=desc)
                except Exception:
                    pass
            db.add(job)
            db.add(video)
            db.commit()
            try:
                from . import plex

                plex.notify_library_changed(
                    host_file_path=video.file_path or str(organized),
                    media_type=getattr(source, "media_type", "video") or "video",
                )
            except Exception:
                pass
        return True
    except Exception as exc:  # noqa: BLE001
        # Session may have been closed for the long yt-dlp run — reopen if needed
        job_pk = getattr(job, "id", None) if job is not None else locals().get("job_id")
        video_pk = getattr(video, "id", None) if video is not None else None
        if db is None:
            db = SessionLocal()
        try:
            if job_pk is not None:
                job = db.get(DownloadJob, int(job_pk))
            if video_pk is not None:
                video = db.get(Video, int(video_pk))
            elif job is not None:
                video = db.get(Video, job.video_id)
        except Exception:
            pass
        if str(exc).strip() == "Cancelled":
            if job is not None:
                job.status = "cancelled"
                job.finished_at = job.finished_at or datetime.utcnow()
                job.error = job.error or "Cancelled"
                db.add(job)
            if video is not None and video.status != VideoStatus.DOWNLOADED.value:
                video.status = VideoStatus.IGNORED.value
                video.error = "Cancelled"
                db.add(video)
            db.commit()
            return True
        if _is_disk_full_error(exc):
            _pause_downloads("disk full")
        if job is not None and job.status != "cancelled":
            job.status = "failed"
            job.error = str(exc)
            if _is_disk_full_error(exc):
                job.error = (
                    f"{exc} — downloads paused. Free disk space, then resume in Activity."
                )
            job.finished_at = datetime.utcnow()
            db.add(job)
        if video is not None and video.status != VideoStatus.IGNORED.value:
            err_s = str(exc)
            if _is_permanent_download_error(err_s):
                video.status = VideoStatus.IGNORED.value
            else:
                video.status = VideoStatus.FAILED.value
                if (
                    _is_auth_block_error(err_s)
                    and "cookies" not in err_s.lower()
                    and "dpapi" not in err_s.lower()
                ):
                    err_s = (
                        f"{err_s} — set cookies in Settings → Download Clients "
                        "(prefer cookies.txt; Chrome/Edge cookies-from-browser "
                        "often fails with DPAPI on Windows), then Retry."
                    )
            video.error = err_s
            db.add(video)
            try:
                from . import notify

                notify.on_download_failure(title=video.title or video.video_id, error=err_s)
            except Exception:
                pass
        try:
            from . import applog

            title = (video.title if video else None) or (video.video_id if video else "?")
            vid = video.video_id if video else "?"
            status = video.status if video else "failed"
            applog.log_error(
                f"Download {status} [{vid}] {title}: {exc}",
                source="downloader",
            )
        except Exception:
            pass
        try:
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
        return True
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass
        if claimed:
            with _lock:
                _active = max(0, _active - 1)


def worker_tick() -> None:
    """Called by scheduler: enqueue wanted, then start downloads up to concurrency.

    Each download runs in its own daemon thread so concurrent_downloads > 1 is real.
    ``process_next_download`` claims under ``_lock`` and is a no-op when slots are full.
    """
    cfg = get_config()
    if cfg.downloads_paused:
        return

    db = SessionLocal()
    try:
        requeue_retryable_failures(db)
        enqueue_wanted(db)
    finally:
        db.close()

    with _lock:
        slots = max(0, int(cfg.concurrent_downloads or 1) - _active)
    for i in range(slots):
        threading.Thread(
            target=process_next_download,
            name=f"ytarr-download-{i}",
            daemon=True,
        ).start()
