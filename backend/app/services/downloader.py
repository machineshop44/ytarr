from __future__ import annotations

import shutil
import threading
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import get_config, set_config
from ..db import SessionLocal
from ..models import DownloadJob, MonitoredSource, Video, VideoStatus
from . import quality, ytdlp


_lock = threading.Lock()
_active = 0

# Refuse to start a download if free space is below this (bytes)
MIN_FREE_BYTES = 500 * 1024 * 1024


def _find_downloaded_file(video_id: str) -> Path | None:
    cfg = get_config()
    needle = f"[{video_id}]"
    for root in (Path(cfg.library_root), Path(cfg.music_library_root)):
        if not root.exists():
            continue
        try:
            for path in root.rglob("*"):
                if path.is_file() and needle in path.name:
                    return path
        except OSError:
            continue
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
                existing = _find_downloaded_file(video.video_id)
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


def enqueue_wanted(db: Session) -> int:
    cfg = get_config()
    if cfg.downloads_paused:
        return 0
    videos = (
        db.query(Video)
        .filter(Video.status == VideoStatus.WANTED.value)
        .order_by(Video.published_at.asc(), Video.id.asc())
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


def _set_progress(db: Session, job_id: int, pct: float) -> None:
    job = db.get(DownloadJob, job_id)
    if not job:
        return
    job.progress = max(0.0, min(100.0, pct))
    db.add(job)
    db.commit()


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


def cancel_all_queued(db: Session) -> int:
    """Cancel every queued job and mark those videos ignored (panic stop)."""
    jobs = db.query(DownloadJob).filter(DownloadJob.status == "queued").all()
    now = datetime.utcnow()
    n = 0
    for job in jobs:
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
    return n


def process_next_download() -> bool:
    """Pick one queued video and download it. Returns True if work was done."""
    global _active
    cfg = get_config()
    if cfg.downloads_paused:
        return False
    with _lock:
        if _active >= max(1, cfg.concurrent_downloads):
            return False
        _active += 1

    db = SessionLocal()
    job: DownloadJob | None = None
    video: Video | None = None
    try:
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

        source = db.get(MonitoredSource, video.source_id)
        media_type = (source.media_type if source else "video") or "video"
        extract_audio = media_type.strip().lower() == "audio"
        if extract_audio:
            library_root = Path(cfg.music_library_root)
            output_template = cfg.music_output_template or cfg.output_template
        else:
            library_root = Path(cfg.library_root)
            output_template = cfg.output_template

        # Same YouTube id already downloaded under another season — reuse file
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
            job.status = "completed"
            job.progress = 100.0
            job.finished_at = datetime.utcnow()
            job.error = None
            video.status = VideoStatus.DOWNLOADED.value
            video.file_path = twin.file_path
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

        job.status = "downloading"
        job.started_at = datetime.utcnow()
        job.progress = 0.0
        video.status = VideoStatus.DOWNLOADING.value
        video.error = None
        db.add(job)
        db.add(video)
        db.commit()

        job_id = job.id
        video_id = video.video_id
        fmt = quality.resolve_format_selector(
            source.quality if source else "",
            default_quality=cfg.default_quality,
            custom_format=cfg.format,
            media_type=media_type,
        )

        def on_progress(pct: float) -> None:
            s = SessionLocal()
            try:
                _set_progress(s, job_id, pct)
            finally:
                s.close()

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

        file_path = ytdlp.download_video(
            ytdlp.video_page_url(video_id),
            library_root=library_root,
            output_template=output_template,
            format_selector=fmt,
            progress_cb=on_progress,
            extract_audio=extract_audio,
            sponsorblock_categories=sb_cats,
        )

        # refresh — honor cancel/ignore that happened during download
        job = db.get(DownloadJob, job_id)
        video = db.get(Video, job.video_id) if job else None
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
            job.status = "completed"
            job.progress = 100.0
            job.finished_at = datetime.utcnow()
            video.status = VideoStatus.DOWNLOADED.value
            video.file_path = str(file_path) if file_path else video.file_path
            video.error = None
            db.add(job)
            db.add(video)
            db.commit()
        return True
    except Exception as exc:  # noqa: BLE001
        if _is_disk_full_error(exc):
            _pause_downloads("disk full")
        if job is not None:
            job = db.get(DownloadJob, job.id) or job
            if job.status != "cancelled":
                job.status = "failed"
                job.error = str(exc)
                if _is_disk_full_error(exc):
                    job.error = (
                        f"{exc} — downloads paused. Free disk space, then resume in Activity."
                    )
                job.finished_at = datetime.utcnow()
                db.add(job)
        if video is not None:
            video = db.get(Video, video.id) or video
            if video.status != VideoStatus.IGNORED.value:
                video.status = VideoStatus.FAILED.value
                video.error = str(exc)
                db.add(video)
        db.commit()
        return True
    finally:
        db.close()
        with _lock:
            _active = max(0, _active - 1)


def worker_tick() -> None:
    """Called by scheduler: enqueue wanted, then process downloads up to concurrency."""
    cfg = get_config()
    if cfg.downloads_paused:
        return

    db = SessionLocal()
    try:
        enqueue_wanted(db)
    finally:
        db.close()

    for _ in range(max(1, cfg.concurrent_downloads)):
        if not process_next_download():
            break
