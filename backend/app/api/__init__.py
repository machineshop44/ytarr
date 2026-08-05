from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import (
    config_file_path,
    get_config,
    get_listen_bind,
    restart_required_for_bind,
    set_config,
    resolve_paths,
    ensure_api_key,
    ensure_auth_credentials,
    regenerate_api_key,
)
from ..db import get_db
from ..models import DownloadJob, MonitoredSource, Video, VideoStatus
from ..schemas import (
    AuthStatusOut,
    DashboardOut,
    DiscoverHitOut,
    DiscoverResponse,
    DiscoverSectionOut,
    DownloadJobOut,
    HealthOut,
    LoginIn,
    LoginOut,
    PlaylistEntriesResponse,
    PlaylistEntryOut,
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
    SystemLogsOut,
    SystemStatusOut,
    VideoOut,
)
from ..services import discover, downloader, monitor, rename, scheduler
from ..services import ytdlp
from .. import auth as auth_mod

router = APIRouter(prefix="/api")


def _settings_out(cfg) -> SettingsOut:
    data = cfg.model_dump()
    data.pop("password_hash", None)
    data["has_password"] = bool((cfg.password_hash or "").strip())
    data["config_path"] = str(config_file_path())
    bind = get_listen_bind()
    if bind:
        data["listen_host"], data["listen_port"] = bind
    else:
        data["listen_host"] = None
        data["listen_port"] = None
    data["restart_required"] = restart_required_for_bind(cfg)
    return SettingsOut(**data)


def _source_out(db: Session, source: MonitoredSource) -> SourceOut:
    counts = dict(
        db.query(Video.status, func.count(Video.id))
        .filter(Video.source_id == source.id)
        .group_by(Video.status)
        .all()
    )
    nested = 0
    if source.source_type == "channel":
        nested = (
            db.query(func.count(MonitoredSource.id))
            .filter(MonitoredSource.parent_source_id == source.id)
            .filter(MonitoredSource.source_type == "playlist")
            .scalar()
            or 0
        )
    return SourceOut(
        id=source.id,
        url=source.url,
        title=source.title,
        yt_id=source.yt_id,
        source_type=source.source_type,
        enabled=source.enabled,
        monitor_mode=source.monitor_mode,
        quality=getattr(source, "quality", "") or "",
        media_type=getattr(source, "media_type", "video") or "video",
        folder_name=source.folder_name,
        poster_path=source.poster_path,
        fanart_path=source.fanart_path,
        parent_source_id=getattr(source, "parent_source_id", None),
        last_checked=source.last_checked,
        initialized=source.initialized,
        created_at=source.created_at,
        video_count=sum(counts.values()),
        wanted_count=counts.get(VideoStatus.WANTED.value, 0)
        + counts.get(VideoStatus.QUEUED.value, 0)
        + counts.get(VideoStatus.DOWNLOADING.value, 0),
        downloaded_count=counts.get(VideoStatus.DOWNLOADED.value, 0),
        nested_playlist_count=int(nested),
    )


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    cfg = get_config()
    ok, version, err = ytdlp.get_version()
    bind = get_listen_bind()
    return HealthOut(
        status="ok" if ok else "degraded",
        ytdlp_ok=ok,
        ytdlp_version=version,
        ytdlp_error=err,
        library_root=cfg.library_root,
        library_exists=Path(cfg.library_root).exists(),
        config_path=str(config_file_path()),
        configured_host=(cfg.host or "").strip(),
        listen_host=bind[0] if bind else None,
        listen_port=bind[1] if bind else None,
        restart_required=restart_required_for_bind(cfg),
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


@router.get("/ping")
def ping() -> dict:
    return {"ok": True, "app": "ytarr"}


@router.get("/auth/status", response_model=AuthStatusOut)
def auth_status(request: Request) -> AuthStatusOut:
    cfg = ensure_auth_credentials(get_config())
    user = auth_mod.session_username(request)
    return AuthStatusOut(
        authentication_method=(cfg.authentication_method or "none"),
        forms_required=auth_mod.forms_enabled(cfg),
        authenticated=bool(user)
        or (not auth_mod.forms_enabled(cfg) and not getattr(cfg, "api_auth_required", True)),
        username=user,
    )


@router.post("/login", response_model=LoginOut)
def login(body: LoginIn, response: Response) -> LoginOut:
    cfg = ensure_auth_credentials(get_config())
    if not auth_mod.forms_enabled(cfg):
        raise HTTPException(status_code=400, detail="Forms authentication is disabled")
    user = (body.username or "").strip()
    if user != (cfg.username or "").strip() or not auth_mod.verify_password(
        body.password or "", cfg.password_hash
    ):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    auth_mod.set_session_cookie(response, user)
    return LoginOut(ok=True, username=user, api_key=cfg.api_key or "")


@router.post("/logout")
def logout(response: Response) -> dict:
    auth_mod.clear_session_cookie(response)
    return {"ok": True}


@router.get("/system/status", response_model=SystemStatusOut)
def system_status() -> SystemStatusOut:
    """Lightweight status for mobile hubs / Arr-style clients."""
    from ..version import app_version

    cfg = get_config()
    method = "forms" if auth_mod.forms_enabled(cfg) else "apiKey"
    return SystemStatusOut(
        version=app_version(),
        authentication=method,
        api_auth_required=bool(getattr(cfg, "api_auth_required", True)),
    )


@router.get("/system/logs", response_model=SystemLogsOut)
def system_logs(max_bytes: int = 256_000) -> SystemLogsOut:
    """Tail of the application log for System → Log (copy/paste friendly)."""
    from ..services import applog

    path = applog.setup_app_logging()
    text = applog.read_log_text(max_bytes=max(8_000, min(max_bytes, 1_000_000)))
    return SystemLogsOut(path=str(path), text=text)


@router.delete("/system/logs")
def clear_system_logs() -> dict:
    """Empty application / tray logs (Sonarr-style clear)."""
    from ..services import applog

    return applog.clear_logs()


@router.post("/videos/clear-failed")
def clear_failed_videos(db: Session = Depends(get_db)) -> dict:
    """Mark all failed videos as ignored — clears the System nav badge."""
    videos = db.query(Video).filter(Video.status == VideoStatus.FAILED.value).all()
    n = 0
    for video in videos:
        video.status = VideoStatus.IGNORED.value
        note = "Cleared from failed"
        if video.error and note not in video.error:
            video.error = f"{video.error} ({note})"
        else:
            video.error = note
        db.add(video)
        monitor.cancel_jobs_for_video(db, video, reason="Cleared from failed")
        n += 1
    db.commit()
    return {"ok": True, "cleared": n}


@router.get("/settings", response_model=SettingsOut)
def get_settings() -> SettingsOut:
    cfg = ensure_auth_credentials(get_config())
    return _settings_out(cfg)


@router.put("/settings", response_model=SettingsOut)
def update_settings(body: SettingsUpdate) -> SettingsOut:
    cfg = ensure_auth_credentials(get_config())
    data = cfg.model_dump()
    payload = body.model_dump(exclude_unset=True)
    new_password = payload.pop("password", None)
    for key, value in payload.items():
        if value is not None and key not in {"api_key", "password_hash"}:
            data[key] = value
    data["api_key"] = cfg.api_key
    data["password_hash"] = cfg.password_hash
    if new_password is not None and str(new_password).strip():
        data["password_hash"] = auth_mod.hash_password(str(new_password).strip())
    if data.get("authentication_method") not in {"none", "forms"}:
        data["authentication_method"] = "forms"
    updated = set_config(resolve_paths(type(cfg)(**data)))
    try:
        scheduler.reschedule_monitor()
    except Exception:
        pass
    return _settings_out(updated)


@router.post("/settings/regenerate-api-key", response_model=SettingsOut)
def regenerate_settings_api_key() -> SettingsOut:
    """Issue a new API key (invalidates the previous one for hubs)."""
    updated = regenerate_api_key()
    return _settings_out(updated)


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


@router.get("/discover", response_model=DiscoverResponse)
def discover_similar(
    max_tags: int = 8,
    per_tag: int = 8,
    enrich: bool = True,
    db: Session = Depends(get_db),
) -> DiscoverResponse:
    """Radarr Discover — suggest channels from tags/topics in your library."""
    max_tags = max(1, min(int(max_tags), 12))
    per_tag = max(1, min(int(per_tag), 12))
    try:
        sections = discover.discover_from_library(
            db,
            max_tags=max_tags,
            per_tag=per_tag,
            enrich_remote=enrich,
        )
    except ytdlp.YtDlpError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    channel_count = (
        db.query(MonitoredSource)
        .filter(MonitoredSource.source_type == "channel")
        .count()
    )
    return DiscoverResponse(
        library_channels=channel_count,
        sections=[
            DiscoverSectionOut(
                tag=s.tag,
                source=s.source,
                based_on=s.based_on,
                weight=s.weight,
                results=[DiscoverHitOut(**h.__dict__) for h in s.results],
            )
            for s in sections
        ],
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


@router.get("/search/entries", response_model=PlaylistEntriesResponse)
def list_url_entries(url: str, limit: int = 100) -> PlaylistEntriesResponse:
    """Preview videos in a channel uploads feed or playlist (members-only filtered)."""
    target = (url or "").strip()
    if len(target) < 8:
        raise HTTPException(status_code=400, detail="URL required")
    limit = max(1, min(int(limit), 200))
    try:
        entries = ytdlp.list_entries(target, limit=limit)
    except ytdlp.YtDlpError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PlaylistEntriesResponse(
        url=target,
        entries=[
            PlaylistEntryOut(
                video_id=e.video_id,
                title=e.title,
                published_at=e.published_at,
                duration=e.duration,
                thumbnail_url=e.thumbnail_url,
                url=e.url,
            )
            for e in entries
        ],
    )


@router.get("/sources", response_model=list[SourceOut])
def list_sources(db: Session = Depends(get_db)) -> list[SourceOut]:
    # Collapse duplicate playlist posters under same-named channels (instant)
    try:
        monitor.link_orphan_playlists_fast(db)
    except Exception:
        db.rollback()
    sources = db.query(MonitoredSource).order_by(MonitoredSource.title.asc()).all()
    return [_source_out(db, s) for s in sources]


@router.post("/sources", response_model=SourceOut)
def create_source(body: SourceCreate, db: Session = Depends(get_db)) -> SourceOut:
    try:
        source = monitor.add_source(
            db,
            body.url,
            mode=body.mode,
            quality=body.quality or "",
            media_type=body.media_type or "video",
            wanted_video_ids=body.wanted_video_ids,
            title=body.title,
            yt_id=body.yt_id,
            thumbnail_url=body.thumbnail_url,
            channel=body.channel,
            parent_source_id=body.parent_source_id,
        )
    except ytdlp.YtDlpError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _source_out(db, source)


@router.post("/sources/{source_id}/backfill")
def backfill_source(
    source_id: int,
    include_ignored: bool = False,
    db: Session = Depends(get_db),
) -> dict:
    source = db.get(MonitoredSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    try:
        return {
            "ok": True,
            **monitor.backfill_source(db, source, include_ignored=include_ignored),
        }
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
    if body.monitor_mode is not None:
        source.monitor_mode = body.monitor_mode
    if body.quality is not None:
        source.quality = body.quality.strip().lower()
    if body.media_type is not None:
        source.media_type = body.media_type
    db.add(source)
    db.commit()
    db.refresh(source)
    return _source_out(db, source)


@router.delete("/sources/{source_id}")
def delete_source(
    source_id: int,
    delete_files: bool = False,
    db: Session = Depends(get_db),
) -> dict:
    source = db.get(MonitoredSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    result = monitor.delete_source_tree(db, source, delete_files=delete_files)
    return {"ok": True, "delete_files": delete_files, **result}


@router.post("/sources/check-all")
def check_all_sources(db: Session = Depends(get_db)) -> dict:
    """Sonarr-style Update All / RSS Sync — refresh every enabled source."""
    try:
        results = monitor.check_all_enabled(db)
        downloader.enqueue_wanted(db)
        return {
            "ok": True,
            "checked": len(results),
            "results": results,
        }
    except ytdlp.YtDlpError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
    if not source:
        raise HTTPException(status_code=404, detail="Poster not found")
    candidates: list[Path] = []
    if source.poster_path:
        candidates.append(Path(source.poster_path))
    candidates.append(monitor._library_root_for(source) / source.folder_name / "poster.jpg")
    for path in candidates:
        if path.is_file():
            return FileResponse(path)
    raise HTTPException(status_code=404, detail="Poster not found")


@router.get("/sources/{source_id}/fanart")
def source_fanart(source_id: int, db: Session = Depends(get_db)):
    source = db.get(MonitoredSource, source_id)
    path = None
    if source and source.fanart_path and Path(source.fanart_path).exists():
        path = source.fanart_path
    elif source and source.poster_path and Path(source.poster_path).exists():
        path = source.poster_path
    if not path:
        raise HTTPException(status_code=404, detail="Fanart not found")
    return FileResponse(path)


@router.get("/videos", response_model=list[VideoOut])
def list_videos(
    status: str | None = None,
    source_id: int | None = None,
    limit: int = 2000,
    db: Session = Depends(get_db),
) -> list[VideoOut]:
    # limit=0 means no cap (selection / admin); otherwise clamp
    q = db.query(Video).join(MonitoredSource)
    if status:
        q = q.filter(Video.status == status)
    if source_id:
        q = q.filter(Video.source_id == source_id)
    q = q.order_by(Video.published_at.desc(), Video.id.desc())
    if limit and limit > 0:
        q = q.limit(min(limit, 20000))
    rows = q.all()
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
    video.error = "Ignored"
    db.add(video)
    monitor.cancel_jobs_for_video(db, video, reason="Ignored")
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
    source_id: int | None = None,
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
    if source_id is not None:
        q = q.join(Video, DownloadJob.video_id == Video.id).filter(Video.source_id == source_id)
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
    """Kick the download worker without blocking the HTTP request.

    Downloads can take minutes; callers (Add New, etc.) must not wait on them.
    The APScheduler tick also runs this work every ~15s.
    """
    import threading

    threading.Thread(
        target=downloader.worker_tick,
        name="ytarr-queue-kick",
        daemon=True,
    ).start()
    return {"ok": True, "started": True}


@router.post("/queue/pause")
def pause_queue() -> dict:
    cfg = get_config()
    cfg.downloads_paused = True
    set_config(cfg)
    return {"ok": True, "downloads_paused": True}


@router.post("/queue/resume")
def resume_queue() -> dict:
    cfg = get_config()
    cfg.downloads_paused = False
    set_config(cfg)
    return {"ok": True, "downloads_paused": False}


@router.post("/queue/clear")
def clear_queue(db: Session = Depends(get_db)) -> dict:
    """Panic stop: cancel all queued jobs and clear wanted items."""
    cfg = get_config()
    cfg.downloads_paused = True
    set_config(cfg)
    cancelled = downloader.cancel_all_queued(db)
    return {"ok": True, "cancelled": cancelled, "downloads_paused": True}


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
