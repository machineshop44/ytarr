from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SourceCreate(BaseModel):
    url: str = Field(min_length=8)
    # new = monitor future uploads only
    # all = download entire channel/playlist now + keep monitoring
    # none = list catalog but never auto-queue (structure only / episode picks)
    # video = download this one video only
    mode: str = Field(default="all", pattern="^(new|all|video|none)$")
    # Empty = inherit Settings default_quality
    quality: str = ""
    # video = library_root; audio = extract to music_library_root
    media_type: str = Field(default="video", pattern="^(video|audio)$")
    # When set, ONLY these YouTube ids are wanted; everything else is ignored.
    # Omit (null) for full-season monitor. Pass [] for monitor-none / no downloads.
    wanted_video_ids: list[str] | None = None
    # Optional hints from search UI — skip a slow yt-dlp resolve when present
    title: str | None = None
    yt_id: str | None = None
    thumbnail_url: str | None = None
    # Uploader / artist name (used as music artist folder for single tracks)
    channel: str | None = None


class SearchHitOut(BaseModel):
    kind: str
    title: str
    url: str
    id: str | None = None
    channel: str | None = None
    thumbnail_url: str | None = None
    duration: int | None = None
    description: str | None = None
    video_count: int | None = None


class SearchResponse(BaseModel):
    query: str
    kind: str
    results: list[SearchHitOut]


class DiscoverHitOut(BaseModel):
    kind: str
    title: str
    url: str
    id: str | None = None
    channel: str | None = None
    thumbnail_url: str | None = None
    duration: int | None = None
    description: str | None = None
    video_count: int | None = None
    already_added: bool = False


class DiscoverSectionOut(BaseModel):
    tag: str
    source: str
    based_on: str | None = None
    weight: int = 0
    results: list[DiscoverHitOut]


class DiscoverResponse(BaseModel):
    sections: list[DiscoverSectionOut]
    library_channels: int = 0


class PlaylistEntryOut(BaseModel):
    video_id: str
    title: str
    published_at: datetime | None = None
    duration: int | None = None
    thumbnail_url: str | None = None
    url: str | None = None


class PlaylistEntriesResponse(BaseModel):
    url: str
    entries: list[PlaylistEntryOut]


class SourceUpdate(BaseModel):
    enabled: bool | None = None
    title: str | None = None
    monitor_mode: str | None = Field(default=None, pattern="^(new|all|video|none)$")
    quality: str | None = None
    media_type: str | None = Field(default=None, pattern="^(video|audio)$")


class SourceOut(BaseModel):
    id: int
    url: str
    title: str
    yt_id: str | None
    source_type: str
    enabled: bool
    monitor_mode: str
    quality: str = ""
    media_type: str = "video"
    folder_name: str
    poster_path: str | None
    fanart_path: str | None
    last_checked: datetime | None
    initialized: bool
    created_at: datetime
    video_count: int = 0
    wanted_count: int = 0
    downloaded_count: int = 0

    model_config = {"from_attributes": True}


class VideoOut(BaseModel):
    id: int
    source_id: int
    video_id: str
    title: str
    published_at: datetime | None
    duration: int | None
    thumbnail_url: str | None
    file_path: str | None
    status: str
    error: str | None
    source_title: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class DownloadJobOut(BaseModel):
    id: int
    video_id: int
    progress: float
    status: str
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    video_title: str | None = None
    youtube_id: str | None = None
    source_title: str | None = None

    model_config = {"from_attributes": True}


class PathMappingOut(BaseModel):
    host_path: str = ""
    plex_path: str = ""


class SettingsOut(BaseModel):
    host: str
    port: int
    data_dir: str
    library_root: str
    music_library_root: str = ""
    ytdlp_path: str
    ffmpeg_path: str = ""
    default_quality: str = "best"
    default_music_quality: str = "best"
    format: str
    music_format: str = "ba/b"
    output_template: str
    music_output_template: str = ""
    poll_interval_minutes: int
    concurrent_downloads: int
    downloads_paused: bool = False
    nocheck_certificates: bool
    sponsorblock_remove: bool = True
    sponsorblock_categories_video: str = "sponsor,selfpromo,interaction,intro,outro"
    sponsorblock_categories_music: str = (
        "music_offtopic,sponsor,selfpromo,interaction,intro,outro"
    )
    path_mappings: list[PathMappingOut] = []
    api_key: str = ""
    api_auth_required: bool = True
    authentication_method: str = "forms"
    username: str = ""
    # password never returned — use has_password
    has_password: bool = False
    # Bind diagnostics (listen_* = socket opened at process start)
    config_path: str = ""
    listen_host: str | None = None
    listen_port: int | None = None
    restart_required: bool = False


class SettingsUpdate(BaseModel):
    library_root: str | None = None
    music_library_root: str | None = None
    ytdlp_path: str | None = None
    ffmpeg_path: str | None = None
    default_quality: str | None = None
    default_music_quality: str | None = None
    format: str | None = None
    music_format: str | None = None
    output_template: str | None = None
    music_output_template: str | None = None
    poll_interval_minutes: int | None = None
    concurrent_downloads: int | None = None
    downloads_paused: bool | None = None
    host: str | None = None
    port: int | None = None
    data_dir: str | None = None
    nocheck_certificates: bool | None = None
    sponsorblock_remove: bool | None = None
    sponsorblock_categories_video: str | None = None
    sponsorblock_categories_music: str | None = None
    path_mappings: list[PathMappingOut] | None = None
    # api_key is regenerated via POST /api/settings/regenerate-api-key only
    api_auth_required: bool | None = None
    authentication_method: str | None = Field(default=None, pattern="^(none|forms)$")
    username: str | None = None
    # Set a new password (plaintext once — stored hashed). Empty = leave unchanged.
    password: str | None = None


class LoginIn(BaseModel):
    username: str
    password: str


class LoginOut(BaseModel):
    ok: bool = True
    username: str
    api_key: str = ""


class AuthStatusOut(BaseModel):
    authentication_method: str
    forms_required: bool
    authenticated: bool
    username: str | None = None


class SystemStatusOut(BaseModel):
    appName: str = "ytarr"
    instanceName: str = "ytarr"
    version: str = "0.1.0"
    authentication: str = "forms"
    api_auth_required: bool = True
    urlBase: str = ""
    branch: str = "main"
    isDebug: bool = False
    isProduction: bool = True
    isAdmin: bool = True


class HealthOut(BaseModel):
    status: str
    ytdlp_ok: bool
    ytdlp_version: str | None
    ytdlp_error: str | None = None
    library_root: str
    library_exists: bool
    config_path: str = ""
    configured_host: str = ""
    listen_host: str | None = None
    listen_port: int | None = None
    restart_required: bool = False


class RenameItemOut(BaseModel):
    video_db_id: int
    youtube_id: str
    title: str
    source_title: str
    current_path: str | None
    new_path: str
    needs_rename: bool
    reason: str | None = None


class RenamePreviewOut(BaseModel):
    items: list[RenameItemOut]
    needs_rename_count: int


class RenameApplyIn(BaseModel):
    source_id: int | None = None
    video_ids: list[int] | None = None


class RenameApplyOut(BaseModel):
    renamed: int
    skipped: int
    planned: int
    errors: list[str]


class DashboardOut(BaseModel):
    sources: int
    enabled_sources: int
    videos: int
    wanted: int
    downloading: int
    downloaded: int
    failed: int
    queue_size: int
    ytdlp_ok: bool
    ytdlp_version: str | None
