from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import get_config
from ..db import SessionLocal
from ..models import DownloadJob, Video, VideoStatus
from . import ytdlp


_lock = threading.Lock()
_active = 0


def enqueue_wanted(db: Session) -> int:
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


def process_next_download() -> bool:
    """Pick one queued video and download it. Returns True if work was done."""
    global _active
    cfg = get_config()
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
            # Also promote any wanted without jobs
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

        def on_progress(pct: float) -> None:
            s = SessionLocal()
            try:
                _set_progress(s, job_id, pct)
            finally:
                s.close()

        file_path = ytdlp.download_video(
            ytdlp.video_page_url(video_id),
            library_root=Path(cfg.library_root),
            output_template=cfg.output_template,
            format_selector=cfg.format,
            progress_cb=on_progress,
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
        if job is not None:
            job = db.get(DownloadJob, job.id) or job
            if job.status != "cancelled":
                job.status = "failed"
                job.error = str(exc)
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
    db = SessionLocal()
    try:
        enqueue_wanted(db)
    finally:
        db.close()

    cfg = get_config()
    for _ in range(max(1, cfg.concurrent_downloads)):
        if not process_next_download():
            break
