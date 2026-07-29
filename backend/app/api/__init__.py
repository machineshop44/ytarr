from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import get_config, set_config
from ..db import get_db
from ..models import DownloadJob, MonitoredSource, Video, VideoStatus
from ..schemas import (
    DashboardOut,
    DownloadJobOut,
    HealthOut,
    RenameApplyIn,
    RenameApplyOut,
    RenameItemOut,
    RenamePreviewOut,
    SearchHitOut,
    SearchResponse,
    SettingsOut,
    SettingsUpdate,
    SourceCreate,
    SourceOut,
    SourceUpdate,
    VideoOut,
)
from ..services import downloader, monitor, rename, scheduler
from ..services import ytdlp

router = APIRouter(prefix="/api")


def _source_out(db: Session, source: MonitoredSource) -> SourceOut:
    counts = dict(
        db.query(Video.status, func.count(Video.id))
        .filter(Video.source_id == source.id)
        .group_by(Video.status)
        .all()
    )
    return SourceOut(
        id=source.id,
        url=source.url,
        title=source.title,
        yt_id=source.yt_id,
        source_type=source.source_type,
        enabled=source.enabled,
        monitor_mode=source.monitor_mode,
        folder_name=source.folder_name,
        poster_path=source.poster_path,
        fanart_path=source.fanart_path,
        last_checked=source.last_checked,
        initialized=source.initialized,
        created_at=source.created_at,
        video_count=sum(counts.values()),
        wanted_count=counts.get(VideoStatus.WANTED.value, 0)
        + counts.get(VideoStatus.QUEUED.value, 0)
        + counts.get(VideoStatus.DOWNLOADING.value, 0),
        downloaded_count=counts.get(VideoStatus.DOWNLOADED.value, 0),
    )


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    cfg = get_config()
    ok, version, err = ytdlp.get_version()
    return HealthOut(
        status="ok" if ok else "degraded",
        ytdlp_ok=ok,
        ytdlp_version=version,
        ytdlp_error=err,
        library_root=cfg.library_root,
        library_exists=Path(cfg.library_root).exists(),
    )


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(db: Session = Depends(get_db)) -> DashboardOut:
    ok, version, _ = ytdlp.get_version()
    statuses = dict(db.query(Video.status, func.count(Video.id)).group_by(Video.status).all())
    queue_size = (
        db.query(func.count(DownloadJob.id))
        .filter(DownloadJob.status.in_(["queued", "downloading"]))
        .scalar()
        or 0
    )
    return DashboardOut(
        sources=db.query(func.count(MonitoredSource.id)).scalar() or 0,
        enabled_sources=db.query(func.count(MonitoredSource.id))
        .filter(MonitoredSource.enabled.is_(True))
        .scalar()
        or 0,
        videos=sum(statuses.values()),
        wanted=statuses.get(VideoStatus.WANTED.value, 0),
        downloading=statuses.get(VideoStatus.DOWNLOADING.value, 0),
        downloaded=statuses.get(VideoStatus.DOWNLOADED.value, 0),
        failed=statuses.get(VideoStatus.FAILED.value, 0),
        queue_size=queue_size,
        ytdlp_ok=ok,
        ytdlp_version=version,
    )


@router.get("/settings", response_model=SettingsOut)
def get_settings() -> SettingsOut:
    return SettingsOut(**get_config().model_dump())


@router.put("/settings", response_model=SettingsOut)
def update_settings(body: SettingsUpdate) -> SettingsOut:
    cfg = get_config()
    data = cfg.model_dump()
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            data[key] = value
    updated = set_config(type(cfg)(**data))
    Path(updated.library_root).mkdir(parents=True, exist_ok=True)
    Path(updated.data_dir).mkdir(parents=True, exist_ok=True)
    try:
        scheduler.reschedule_monitor()
    except Exception:
        pass
    return SettingsOut(**updated.model_dump())


@router.get("/search", response_model=SearchResponse)
def search_youtube(
    q: str,
    kind: str = "channel",
    limit: int = 12,
) -> SearchResponse:
    query = (q or "").strip()
    if len(query) < 2:
        raise HTTPException(status_code=400, detail="Query must be at least 2 characters")
    try:
        hits = ytdlp.search_youtube(query, kind=kind, limit=limit)
    except ytdlp.YtDlpError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SearchResponse(
        query=query,
        kind=kind,
        results=[SearchHitOut(**h.__dict__) for h in hits],
    )


@router.get("/search/playlists", response_model=SearchResponse)
def list_channel_playlists(url: str, limit: int = 50) -> SearchResponse:
    """Browse a channel's playlists (Lidarr-style album picker)."""
    channel_url = (url or "").strip()
    if len(channel_url) < 8:
        raise HTTPException(status_code=400, detail="Channel URL required")
    try:
        hits = ytdlp.list_channel_playlists(channel_url, limit=limit)
    except ytdlp.YtDlpError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SearchResponse(
        query=channel_url,
        kind="playlist",
        results=[SearchHitOut(**h.__dict__) for h in hits],
    )


@router.get("/sources", response_model=list[SourceOut])
def list_sources(db: Session = Depends(get_db)) -> list[SourceOut]:
    sources = db.query(MonitoredSource).order_by(MonitoredSource.title.asc()).all()
    return [_source_out(db, s) for s in sources]


@router.post("/sources", response_model=SourceOut)
def create_source(body: SourceCreate, db: Session = Depends(get_db)) -> SourceOut:
    try:
        source = monitor.add_source(db, body.url, mode=body.mode)
    except ytdlp.YtDlpError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _source_out(db, source)


@router.post("/sources/{source_id}/backfill")
def backfill_source(source_id: int, db: Session = Depends(get_db)) -> dict:
    source = db.get(MonitoredSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    try:
        return {"ok": True, **monitor.backfill_source(db, source)}
    except ytdlp.YtDlpError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/sources/{source_id}", response_model=SourceOut)
def get_source(source_id: int, db: Session = Depends(get_db)) -> SourceOut:
    source = db.get(MonitoredSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    return _source_out(db, source)


@router.patch("/sources/{source_id}", response_model=SourceOut)
def patch_source(
    source_id: int, body: SourceUpdate, db: Session = Depends(get_db)
) -> SourceOut:
    source = db.get(MonitoredSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    if body.enabled is not None:
        source.enabled = body.enabled
    if body.title is not None:
        source.title = body.title
    db.add(source)
    db.commit()
    db.refresh(source)
    return _source_out(db, source)


@router.delete("/sources/{source_id}")
def delete_source(source_id: int, db: Session = Depends(get_db)) -> dict:
    source = db.get(MonitoredSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    db.delete(source)
    db.commit()
    return {"ok": True}


@router.post("/sources/{source_id}/check")
def check_now(source_id: int, db: Session = Depends(get_db)) -> dict:
    source = db.get(MonitoredSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    try:
        result = monitor.check_source(db, source)
        downloader.enqueue_wanted(db)
        return {"ok": True, **result}
    except ytdlp.YtDlpError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/sources/{source_id}/refresh-artwork", response_model=SourceOut)
def refresh_artwork(source_id: int, db: Session = Depends(get_db)) -> SourceOut:
    source = db.get(MonitoredSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    try:
        source = monitor.ensure_artwork(db, source)
    except ytdlp.YtDlpError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _source_out(db, source)


@router.get("/sources/{source_id}/poster")
def source_poster(source_id: int, db: Session = Depends(get_db)):
    source = db.get(MonitoredSource, source_id)
    if not source or not source.poster_path or not Path(source.poster_path).exists():
        raise HTTPException(status_code=404, detail="Poster not found")
    return FileResponse(source.poster_path)


@router.get("/videos", response_model=list[VideoOut])
def list_videos(
    status: str | None = None,
    source_id: int | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
) -> list[VideoOut]:
    q = db.query(Video).join(MonitoredSource)
    if status:
        q = q.filter(Video.status == status)
    if source_id:
        q = q.filter(Video.source_id == source_id)
    rows = q.order_by(Video.published_at.desc(), Video.id.desc()).limit(limit).all()
    out: list[VideoOut] = []
    for v in rows:
        item = VideoOut.model_validate(v)
        item.source_title = v.source.title if v.source else None
        out.append(item)
    return out


@router.post("/videos/{video_id}/retry", response_model=VideoOut)
def retry_video(video_id: int, db: Session = Depends(get_db)) -> VideoOut:
    video = db.get(Video, video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    video.status = VideoStatus.WANTED.value
    video.error = None
    db.add(video)
    db.commit()
    downloader.enqueue_wanted(db)
    db.refresh(video)
    item = VideoOut.model_validate(video)
    item.source_title = video.source.title if video.source else None
    return item


@router.post("/videos/{video_id}/ignore", response_model=VideoOut)
def ignore_video(video_id: int, db: Session = Depends(get_db)) -> VideoOut:
    video = db.get(Video, video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    video.status = VideoStatus.IGNORED.value
    db.add(video)
    db.commit()
    db.refresh(video)
    item = VideoOut.model_validate(video)
    item.source_title = video.source.title if video.source else None
    return item


def _job_out(job: DownloadJob) -> DownloadJobOut:
    item = DownloadJobOut.model_validate(job)
    if job.video:
        item.video_title = job.video.title
        item.youtube_id = job.video.video_id
        item.source_title = job.video.source.title if job.video.source else None
    return item


@router.get("/queue", response_model=list[DownloadJobOut])
def list_queue(
    status: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> list[DownloadJobOut]:
    """List download jobs.

    status:
      - omitted / all — recent jobs of any status
      - active — queued + downloading (Activity Queue tab)
      - history — completed + failed + cancelled (Activity History tab)
      - or a specific status / comma-separated list
    """
    limit = max(1, min(limit, 500))
    q = db.query(DownloadJob)
    if status and status not in {"all", "*"}:
        if status == "active":
            statuses = ["queued", "downloading"]
        elif status == "history":
            statuses = ["completed", "failed", "cancelled"]
        else:
            statuses = [s.strip() for s in status.split(",") if s.strip()]
        if statuses:
            q = q.filter(DownloadJob.status.in_(statuses))
    if status == "active":
        jobs = q.order_by(DownloadJob.id.asc()).limit(limit).all()
    else:
        jobs = q.order_by(DownloadJob.id.desc()).limit(limit).all()
    return [_job_out(job) for job in jobs]


@router.post("/queue/process")
def process_queue() -> dict:
    downloader.worker_tick()
    return {"ok": True}


@router.post("/queue/{job_id}/retry", response_model=DownloadJobOut)
def retry_queue_job(job_id: int, db: Session = Depends(get_db)) -> DownloadJobOut:
    job = db.get(DownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    video = db.get(Video, job.video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    if job.status not in {"failed", "cancelled"}:
        raise HTTPException(status_code=400, detail="Only failed or cancelled jobs can be retried")
    video.status = VideoStatus.WANTED.value
    video.error = None
    db.add(video)
    db.commit()
    downloader.enqueue_wanted(db)
    new_job = (
        db.query(DownloadJob)
        .filter(DownloadJob.video_id == video.id, DownloadJob.status == "queued")
        .order_by(DownloadJob.id.desc())
        .first()
    )
    if not new_job:
        raise HTTPException(status_code=500, detail="Failed to enqueue retry job")
    return _job_out(new_job)


@router.post("/queue/{job_id}/cancel", response_model=DownloadJobOut)
def cancel_queue_job(job_id: int, db: Session = Depends(get_db)) -> DownloadJobOut:
    """Cancel a queued job, or mark an in-progress download ignored (v1: no process kill)."""
    job = db.get(DownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in {"queued", "downloading"}:
        raise HTTPException(status_code=400, detail="Only queued or downloading jobs can be cancelled")
    video = db.get(Video, job.video_id)
    was_downloading = job.status == "downloading"
    job.status = "cancelled"
    job.finished_at = datetime.utcnow()
    if was_downloading:
        job.error = "Cancelled (active yt-dlp may finish; file will be ignored if it completes)"
    else:
        job.error = "Cancelled"
    db.add(job)
    if video:
        video.status = VideoStatus.IGNORED.value
        video.error = job.error
        db.add(video)
    db.commit()
    db.refresh(job)
    return _job_out(job)


@router.get("/rename/preview", response_model=RenamePreviewOut)
def rename_preview(
    source_id: int | None = None,
    db: Session = Depends(get_db),
) -> RenamePreviewOut:
    plans = rename.preview_renames(db, source_id=source_id)
    items = [
        RenameItemOut(
            video_db_id=p.video_db_id,
            youtube_id=p.youtube_id,
            title=p.title,
            source_title=p.source_title,
            current_path=p.current_path,
            new_path=p.new_path,
            needs_rename=p.needs_rename,
            reason=p.reason,
        )
        for p in plans
    ]
    return RenamePreviewOut(
        items=items,
        needs_rename_count=sum(1 for i in items if i.needs_rename),
    )


@router.post("/rename/apply", response_model=RenameApplyOut)
def rename_apply(body: RenameApplyIn, db: Session = Depends(get_db)) -> RenameApplyOut:
    result = rename.apply_renames(
        db,
        source_id=body.source_id,
        video_ids=body.video_ids,
    )
    return RenameApplyOut(**result)
