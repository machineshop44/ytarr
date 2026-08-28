from __future__ import annotations

from datetime import datetime
from pathlib import Path
import threading

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

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


def _source_out(
    db: Session,
    source: MonitoredSource,
    *,
    counts: dict[str, int] | None = None,
    nested: int | None = None,
) -> SourceOut:
    if counts is None:
        counts = dict(
            db.query(Video.status, func.count(Video.id))
            .filter(Video.source_id == source.id)
            .group_by(Video.status)
            .all()
        )
    if nested is None:
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
        description=getattr(source, "description", None),
        subscriber_count=getattr(source, "subscriber_count", None),
        quality=getattr(source, "quality", "") or "",
        media_type=getattr(source, "media_type", "video") or "video",
        folder_name=source.folder_name,
        poster_path=source.poster_path,
        fanart_path=source.fanart_path,
        parent_source_id=getattr(source, "parent_source_id", None),
        tags=getattr(source, "tags", "") or "",
        season_number=int(getattr(source, "season_number", None) or 1),
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
    warnings: list[str] = []
    cookies_file = (getattr(cfg, "ytdlp_cookies_path", "") or "").strip()
    browser = (getattr(cfg, "ytdlp_cookies_from_browser", "") or "").strip().lower()
    if browser in {"chrome", "edge", "brave", "chromium"} and not (
        cookies_file and Path(cookies_file).is_file()
    ):
        warnings.append(
            f"Cookies from browser is set to {browser.title()} without a cookies.txt file. "
            "Chrome/Edge often lock or encrypt the cookie DB on Windows — prefer Off + "
            "a Netscape cookies.txt, or Firefox. Settings → Download Clients."
        )
    status = "ok" if ok and not warnings else ("degraded" if not ok else "ok")
    if warnings and ok:
        status = "warning"
    return HealthOut(
        status=status,
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
        warnings=warnings,
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
        downloads_paused=bool(get_config().downloads_paused),
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
    sources = db.query(MonitoredSource).order_by(MonitoredSource.title.asc()).all()
    if not sources:
        return []
    ids = [s.id for s in sources]
    count_rows = (
        db.query(Video.source_id, Video.status, func.count(Video.id))
        .filter(Video.source_id.in_(ids))
        .group_by(Video.source_id, Video.status)
        .all()
    )
    counts_by_source: dict[int, dict[str, int]] = {i: {} for i in ids}
    for source_id, status, n in count_rows:
        counts_by_source.setdefault(int(source_id), {})[str(status)] = int(n)
    nested_rows = (
        db.query(MonitoredSource.parent_source_id, func.count(MonitoredSource.id))
        .filter(MonitoredSource.parent_source_id.in_(ids))
        .filter(MonitoredSource.source_type == "playlist")
        .group_by(MonitoredSource.parent_source_id)
        .all()
    )
    nested_by_parent = {int(pid): int(n) for pid, n in nested_rows if pid is not None}
    return [
        _source_out(
            db,
            s,
            counts=counts_by_source.get(s.id, {}),
            nested=nested_by_parent.get(s.id, 0) if s.source_type == "channel" else 0,
        )
        for s in sources
    ]


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
    old_quality = (source.quality or "").strip().lower()
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
    if body.tags is not None:
        # Normalize: comma-separated unique labels
        parts = [p.strip() for p in str(body.tags).split(",") if p.strip()]
        source.tags = ", ".join(dict.fromkeys(parts))
    db.add(source)
    db.commit()
    db.refresh(source)
    # Quality upgrade: re-queue downloaded episodes when quality preset changes
    new_quality = (source.quality or "").strip().lower()
    if body.quality is not None and new_quality and new_quality != old_quality:
        bumped = 0
        for video in db.query(Video).filter(Video.source_id == source.id).all():
            if video.status == VideoStatus.DOWNLOADED.value:
                video.status = VideoStatus.WANTED.value
                video.error = f"Quality upgrade → {new_quality}"
                db.add(video)
                bumped += 1
        if bumped:
            db.commit()
            downloader.enqueue_wanted(db)
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
    if delete_files:
        try:
            from ..services import plex

            media = getattr(source, "media_type", "video") or "video"
            plex.notify_library_changed(media_type=media)
        except Exception:
            pass
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
def refresh_artwork(
    source_id: int,
    force: bool = True,
    db: Session = Depends(get_db),
) -> SourceOut:
    source = db.get(MonitoredSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    try:
        source = monitor.ensure_artwork(db, source, force=force)
    except ytdlp.YtDlpError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _source_out(db, source)


@router.post("/sources/{source_id}/refresh-metadata", response_model=SourceOut)
def refresh_source_metadata(source_id: int, db: Session = Depends(get_db)) -> SourceOut:
    """Backfill the YouTube About text / subscriber count for an existing source."""
    source = db.get(MonitoredSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    try:
        monitor.refresh_source_metadata(db, source)
    except ytdlp.YtDlpError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
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
    q = db.query(Video).options(joinedload(Video.source))
    if status == "cutoff":
        # Quality-upgrade requeues (Sonarr Cutoff Unmet analogue)
        q = q.filter(Video.error.ilike("%Quality upgrade%")).filter(
            Video.status.in_(
                [
                    VideoStatus.WANTED.value,
                    VideoStatus.QUEUED.value,
                    VideoStatus.DOWNLOADING.value,
                    VideoStatus.FAILED.value,
                ]
            )
        )
    elif status:
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
    video.retry_count = 0
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
    q = db.query(DownloadJob).options(
        joinedload(DownloadJob.video).joinedload(Video.source),
    )
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


_queue_kick_lock = threading.Lock()
_queue_kick_running = False


@router.post("/queue/process")
def process_queue() -> dict:
    """Kick the download worker without blocking the HTTP request.

    Downloads can take minutes; callers (Add New, etc.) must not wait on them.
    The APScheduler tick also runs this work every ~15s.
    """
    global _queue_kick_running
    with _queue_kick_lock:
        if _queue_kick_running:
            return {"ok": True, "started": False, "busy": True}
        _queue_kick_running = True

    def _run() -> None:
        global _queue_kick_running
        try:
            downloader.worker_tick()
        finally:
            with _queue_kick_lock:
                _queue_kick_running = False

    threading.Thread(
        target=_run,
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
    video.retry_count = 0
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
    """Cancel a queued or in-progress download and stop yt-dlp if it is running."""
    job = db.get(DownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in {"queued", "downloading"}:
        raise HTTPException(status_code=400, detail="Only queued or downloading jobs can be cancelled")
    video = db.get(Video, job.video_id)
    job.status = "cancelled"
    job.finished_at = datetime.utcnow()
    job.error = "Cancelled"
    db.add(job)
    if video:
        video.status = VideoStatus.IGNORED.value
        video.error = job.error
        db.add(video)
    db.commit()
    db.refresh(job)
    downloader.cancel_job_process(job_id)
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
    if result.get("renamed"):
        try:
            from ..services import plex

            plex.notify_library_changed(media_type="video")
            plex.notify_library_changed(media_type="audio")
        except Exception:
            pass
    return RenameApplyOut(**result)


@router.get("/connect/plex/sections")
def plex_sections() -> dict:
    from ..services import plex

    try:
        sections = plex.list_sections()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"sections": sections}


@router.post("/connect/plex/test")
def plex_test() -> dict:
    from ..services import plex

    return plex.test_connection()


@router.post("/connect/plex/refresh")
def plex_refresh(media_type: str = "video", path: str | None = None) -> dict:
    from ..services import plex

    cfg = get_config()
    sid = (
        (cfg.plex_music_section_id if media_type == "audio" else cfg.plex_video_section_id)
        or ""
    ).strip()
    if not sid:
        raise HTTPException(status_code=400, detail="Configure a Plex section id first")
    return plex.refresh_section(sid, path=path)


@router.get("/system/tasks")
def system_tasks() -> dict:
    return {"tasks": scheduler.list_tasks()}


@router.post("/system/tasks/{task_id}/run")
def run_system_task(task_id: str) -> dict:
    from ..db import SessionLocal

    if task_id == "monitor":
        db = SessionLocal()
        try:
            results = monitor.check_all_enabled(db)
            downloader.enqueue_wanted(db)
            return {"ok": True, "checked": len(results)}
        finally:
            db.close()
    if task_id == "downloads":
        downloader.worker_tick()
        return {"ok": True}
    if task_id == "ytdlp_update":
        from ..services import ytdlp_update

        return ytdlp_update.maybe_update_ytdlp(force=True)
    raise HTTPException(status_code=404, detail="Unknown task")


@router.get("/system/backup")
def list_system_backups() -> dict:
    from ..services import backup

    return {"backups": backup.list_backups()}


@router.post("/system/backup")
def create_system_backup() -> dict:
    from ..services import backup

    return backup.create_backup()


@router.post("/system/backup/restore")
def restore_system_backup(name: str) -> dict:
    from ..services import backup

    try:
        return backup.restore_backup(name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/system/updates")
def system_updates() -> dict:
    from ..version import app_version

    ok, version, err = ytdlp.get_version()
    return {
        "app_version": app_version(),
        "ytdlp_ok": ok,
        "ytdlp_version": version,
        "ytdlp_error": err,
        "note": "yt-dlp/ffmpeg auto-update every 24h; use Run update to refresh now.",
    }


@router.post("/system/updates/ytdlp")
def trigger_ytdlp_update() -> dict:
    from ..services import ytdlp_update

    return ytdlp_update.maybe_update_ytdlp()


@router.get("/calendar")
def calendar_events(
    start: str | None = None,
    end: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    """Episodes with publish dates in range (monitored sources)."""
    from datetime import timedelta

    now = datetime.utcnow()
    try:
        def _parse(raw: str | None, default: datetime) -> datetime:
            if not raw:
                return default
            text = raw.strip().replace("Z", "+00:00")
            return datetime.fromisoformat(text).replace(tzinfo=None)

        start_dt = _parse(start, now - timedelta(days=14))
        end_dt = _parse(end, now + timedelta(days=30))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid start/end") from exc
    q = (
        db.query(Video)
        .options(joinedload(Video.source))
        .join(MonitoredSource)
        .filter(MonitoredSource.enabled.is_(True))
        .filter(Video.published_at.isnot(None))
        .filter(Video.published_at >= start_dt)
        .filter(Video.published_at <= end_dt)
        .order_by(Video.published_at.asc())
        .limit(500)
    )
    events = []
    for v in q.all():
        events.append(
            {
                "id": v.id,
                "title": v.title,
                "video_id": v.video_id,
                "status": v.status,
                "published_at": v.published_at.isoformat() if v.published_at else None,
                "source_id": v.source_id,
                "source_title": v.source.title if v.source else None,
            }
        )
    return {"events": events, "start": start_dt.isoformat(), "end": end_dt.isoformat()}


@router.get("/blocklist")
def blocklist(limit: int = 200, db: Session = Depends(get_db)) -> dict:
    limit = max(1, min(int(limit), 500))
    rows = (
        db.query(Video)
        .options(joinedload(Video.source))
        .filter(Video.status == VideoStatus.IGNORED.value)
        .order_by(Video.updated_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "items": [
            {
                "id": v.id,
                "title": v.title,
                "video_id": v.video_id,
                "error": v.error,
                "source_id": v.source_id,
                "source_title": v.source.title if v.source else None,
                "updated_at": v.updated_at.isoformat() if v.updated_at else None,
            }
            for v in rows
        ]
    }


@router.delete("/blocklist/{video_id}")
def unblock_video(video_id: int, db: Session = Depends(get_db)) -> dict:
    video = db.get(Video, video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Not found")
    video.status = VideoStatus.SEEN.value
    video.error = None
    db.add(video)
    db.commit()
    return {"ok": True}


@router.get("/import/scan")
def import_scan(limit: int = 200, db: Session = Depends(get_db)) -> dict:
    from ..services import manual_import

    return {"items": manual_import.scan_orphans(db, limit=limit)}


@router.post("/import/apply")
def import_apply(body: dict, db: Session = Depends(get_db)) -> dict:
    from ..services import manual_import, plex

    items = body.get("items") or []
    source_id = body.get("source_id")
    result = manual_import.import_files(db, items, source_id=source_id)
    if result.get("imported"):
        try:
            plex.notify_library_changed(media_type="video")
        except Exception:
            pass
    return result


@router.get("/sources/{source_id}/interactive-search")
def interactive_search(
    source_id: int,
    q: str | None = None,
    limit: int = 20,
    db: Session = Depends(get_db),
) -> dict:
    """Search YouTube for episodes related to this source (Arr Interactive Search)."""
    source = db.get(MonitoredSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    query = (q or source.title or "").strip()
    if len(query) < 2:
        raise HTTPException(status_code=400, detail="Query too short")
    try:
        hits = ytdlp.search_youtube(query, kind="video", limit=limit)
    except ytdlp.YtDlpError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    known = {
        v.video_id: v.status
        for v in db.query(Video).filter(Video.source_id == source_id).all()
    }
    results = []
    for h in hits:
        vid = h.id or ""
        results.append(
            {
                **h.__dict__,
                "in_library": vid in known,
                "library_status": known.get(vid),
            }
        )
    return {"query": query, "results": results}


@router.post("/sources/{source_id}/interactive-search/grab")
def grab_interactive_result(
    source_id: int,
    body: dict,
    db: Session = Depends(get_db),
) -> dict:
    """Queue a YouTube video from Interactive Search under this series (Arr Grab)."""
    source = db.get(MonitoredSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    video_id = str(body.get("video_id") or body.get("id") or "").strip()
    title = str(body.get("title") or "Untitled").strip() or "Untitled"
    if not video_id:
        raise HTTPException(status_code=400, detail="video_id required")
    existing = (
        db.query(Video)
        .filter(Video.source_id == source_id, Video.video_id == video_id)
        .one_or_none()
    )
    if existing:
        if existing.status == VideoStatus.DOWNLOADED.value and existing.file_path:
            return {
                "ok": True,
                "already": True,
                "video_id": existing.id,
                "status": existing.status,
                "message": "Already downloaded for this series",
            }
        existing.status = VideoStatus.WANTED.value
        existing.error = None
        existing.retry_count = 0
        if title and title != "Untitled":
            existing.title = title[:512]
        db.add(existing)
        video = existing
        created = False
    else:
        video = Video(
            source_id=source.id,
            video_id=video_id,
            title=title[:512],
            status=VideoStatus.WANTED.value,
        )
        db.add(video)
        created = True
    db.commit()
    db.refresh(video)
    downloader.enqueue_wanted(db)
    try:
        from ..services import notify

        notify.on_grab(title=video.title, video_id=video.video_id, source_title=source.title)
    except Exception:
        pass
    return {
        "ok": True,
        "created": created,
        "video_id": video.id,
        "youtube_id": video.video_id,
        "status": video.status,
        "message": "Queued for download",
    }


@router.get("/tags")
def list_tags(db: Session = Depends(get_db)) -> dict:
    tags: dict[str, int] = {}
    for (raw,) in db.query(MonitoredSource.tags).all():
        for part in str(raw or "").split(","):
            p = part.strip()
            if p:
                tags[p] = tags.get(p, 0) + 1
    return {
        "tags": sorted(tags.keys(), key=str.lower),
        "counts": {k: tags[k] for k in sorted(tags.keys(), key=str.lower)},
    }


@router.post("/tags/rename")
def rename_tag(body: dict, db: Session = Depends(get_db)) -> dict:
    old = str(body.get("from") or body.get("old") or "").strip()
    new = str(body.get("to") or body.get("new") or "").strip()
    if not old or not new:
        raise HTTPException(status_code=400, detail="from and to required")
    if old.lower() == new.lower() and old != new:
        # case-only rename — still apply
        pass
    elif old.lower() == new.lower():
        return {"ok": True, "updated": 0}
    updated = 0
    for source in db.query(MonitoredSource).all():
        parts = [p.strip() for p in str(source.tags or "").split(",") if p.strip()]
        if not any(p.lower() == old.lower() for p in parts):
            continue
        next_parts: list[str] = []
        seen: set[str] = set()
        for p in parts:
            label = new if p.lower() == old.lower() else p
            key = label.lower()
            if key in seen:
                continue
            seen.add(key)
            next_parts.append(label)
        source.tags = ", ".join(next_parts)
        db.add(source)
        updated += 1
    db.commit()
    return {"ok": True, "updated": updated, "from": old, "to": new}


@router.delete("/tags/{tag_name}")
def delete_tag(tag_name: str, db: Session = Depends(get_db)) -> dict:
    target = (tag_name or "").strip()
    if not target:
        raise HTTPException(status_code=400, detail="tag required")
    updated = 0
    for source in db.query(MonitoredSource).all():
        parts = [p.strip() for p in str(source.tags or "").split(",") if p.strip()]
        next_parts = [p for p in parts if p.lower() != target.lower()]
        if len(next_parts) == len(parts):
            continue
        source.tags = ", ".join(next_parts)
        db.add(source)
        updated += 1
    db.commit()
    return {"ok": True, "updated": updated, "tag": target}
