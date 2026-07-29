from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler

from ..config import get_config
from ..db import SessionLocal
from . import downloader, monitor

_scheduler: BackgroundScheduler | None = None


def _monitor_job() -> None:
    db = SessionLocal()
    try:
        monitor.check_all_enabled(db)
    finally:
        db.close()


def _download_job() -> None:
    downloader.worker_tick()


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
