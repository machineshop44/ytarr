from __future__ import annotations

from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from ..config import get_config
from ..db import SessionLocal
from . import downloader, monitor, ytdlp_update

_scheduler: BackgroundScheduler | None = None


def _monitor_job() -> None:
    db = SessionLocal()
    try:
        monitor.check_all_enabled(db)
    finally:
        db.close()


def _download_job() -> None:
    downloader.worker_tick()


def _ytdlp_update_job() -> None:
    """Refresh yt-dlp and check/refresh ffmpeg on the same schedule."""
    try:
        ytdlp_update.maybe_update_ytdlp()
    except Exception:
        # Never let updater crashes take down the scheduler
        pass


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler

    cfg = get_config()
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        _monitor_job,
        "interval",
        minutes=max(1, cfg.poll_interval_minutes),
        id="monitor",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _download_job,
        "interval",
        seconds=15,
        id="downloads",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    # First tools check ~30s after start (let UI bind), then every 24h.
    # Updates yt-dlp and verifies/refreshes ffmpeg in the same pass.
    scheduler.add_job(
        _ytdlp_update_job,
        "interval",
        hours=24,
        id="ytdlp_update",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=30),
    )
    scheduler.start()
    _scheduler = scheduler
    return scheduler


def reschedule_monitor() -> None:
    if not _scheduler:
        return
    cfg = get_config()
    _scheduler.reschedule_job(
        "monitor",
        trigger="interval",
        minutes=max(1, cfg.poll_interval_minutes),
    )


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def list_tasks() -> list[dict]:
    """Arr-style System → Tasks snapshot."""
    if not _scheduler:
        return []
    out: list[dict] = []
    for job in _scheduler.get_jobs():
        next_run = job.next_run_time
        out.append(
            {
                "id": job.id,
                "name": job.name or job.id,
                "next_run_time": next_run.isoformat() if next_run else None,
                "trigger": str(job.trigger),
            }
        )
    return out
