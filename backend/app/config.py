from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings

from .paths import project_root


DEFAULT_OUTPUT_TEMPLATE = (
    "%(uploader,playlist_title|Unknown)s/"
    "%(upload_date>%Y-%m-%d)s - %(title).200B [%(id)s].%(ext)s"
)
DEFAULT_MUSIC_OUTPUT_TEMPLATE = (
    "%(uploader,artist|Unknown)s/%(title).200B.%(ext)s"
)

ROOT_DIR = project_root()
DEFAULT_CONFIG_PATH = ROOT_DIR / "config.yaml"
DEFAULT_DATA_DIR = ROOT_DIR / "data"
DEFAULT_LIBRARY_DIR = ROOT_DIR / "library"
DEFAULT_MUSIC_LIBRARY_DIR = ROOT_DIR / "music"


def normalize_bind_host(host: str | None) -> str:
    """Sanitize bind address — trailing dots (0.0.0.0.) break getaddrinfo on Windows."""
    h = (host or "").strip()
    while h.endswith("."):
        h = h[:-1].rstrip()
    return h or "127.0.0.1"


class PathMapping(BaseModel):
    """Sonarr-style remote path mapping: host path ↔ path Plex (or another machine) sees."""

    host_path: str = ""
    plex_path: str = ""


class AppConfig(BaseModel):
    # Default LAN/WAN-reachable so port-forward + Arrs Hub Mobile work.
    # Opt into localhost-only with host: 127.0.0.1 in config.yaml.
    host: str = "0.0.0.0"
    port: int = 8199
    data_dir: str = str(DEFAULT_DATA_DIR)
    library_root: str = str(DEFAULT_LIBRARY_DIR)
    music_library_root: str = str(DEFAULT_MUSIC_LIBRARY_DIR)
    ytdlp_path: str = "yt-dlp"
    # Empty = auto-detect bundled tools/ffmpeg, then PATH
    ffmpeg_path: str = ""
    # Optional Netscape cookies.txt for age-gate / bot 403s (preferred on Windows)
    ytdlp_cookies_path: str = ""
    # Optional: chrome | edge | firefox | brave | chromium (empty = off).
    # Ignored when ytdlp_cookies_path points to an existing file. Chrome/Edge on
    # Windows often fail with DPAPI / App-Bound encryption — prefer cookies.txt
    # or Firefox (see yt-dlp#10927).
    ytdlp_cookies_from_browser: str = ""
    # Named preset: best | 2160p | 1080p | 720p | 480p | worst | custom
    default_quality: str = "best"
    # Music: best | 320k | 192k | 128k | 64k | worst | custom
    default_music_quality: str = "best"
    # Used when default_quality (or source quality) is "custom" (video)
    format: str = "bv*+ba/b"
    # Used when default_music_quality / music source quality is "custom"
    music_format: str = "ba/b"
    output_template: str = DEFAULT_OUTPUT_TEMPLATE
    music_output_template: str = DEFAULT_MUSIC_OUTPUT_TEMPLATE
    poll_interval_minutes: int = 30
    concurrent_downloads: int = 1
    # When True, worker will not start new downloads (Activity pause / disk-full)
    downloads_paused: bool = False
    # Prefer real HTTPS certificate verification. Only enable nocheck on broken
    # networks (e.g. captive/guest Wi‑Fi with SSL inspection). Use VPN when possible.
    nocheck_certificates: bool = False
    # Cut SponsorBlock-marked segments via ffmpeg (community data; skips when unmarked)
    sponsorblock_remove: bool = True
    sponsorblock_categories_video: str = "sponsor,selfpromo,interaction,intro,outro"
    sponsorblock_categories_music: str = (
        "music_offtopic,sponsor,selfpromo,interaction,intro,outro"
    )
    # Optional mappings so docs / future agents know how host paths appear on Plex
    path_mappings: list[PathMapping] = Field(default_factory=list)
    # Settings → Connect → Plex (Arr-style library refresh)
    plex_enabled: bool = False
    plex_url: str = "http://127.0.0.1:32400"
    plex_token: str = ""
    plex_video_section_id: str = ""
    plex_music_section_id: str = ""
    plex_refresh_debounce_seconds: int = 45
    # Settings → Connect → Webhook (Discord-compatible JSON)
    connect_webhook_url: str = ""
    connect_on_download: bool = True
    connect_on_failure: bool = True
    connect_on_grab: bool = False
    # Sonarr-style API key for mobile hubs / remote clients (X-Api-Key)
    api_key: str = ""
    # When True, /api/* requires X-Api-Key or ?apikey= (ignored when Forms session is valid)
    api_auth_required: bool = True
    # none | forms — Forms matches Sonarr username/password login for the UI
    authentication_method: str = "forms"
    username: str = ""
    # pbkdf2_sha256$rounds$salt$hash — never store plaintext
    password_hash: str = ""

    @field_validator("host", mode="before")
    @classmethod
    def _strip_trailing_dot_host(cls, v: Any) -> str:
        return normalize_bind_host(v if isinstance(v, str) or v is None else str(v))


class Settings(BaseSettings):
    config_path: str = str(DEFAULT_CONFIG_PATH)

    def load(self) -> AppConfig:
        path = Path(self.config_path)
        if not path.is_absolute():
            path = ROOT_DIR / path
        data: dict[str, Any] = {}
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f) or {}
                if isinstance(loaded, dict):
                    data = loaded
        raw_host = data.get("host")
        cfg = resolve_paths(AppConfig(**data))
        # Auto-fix typos like 0.0.0.0. that break Windows getaddrinfo
        if isinstance(raw_host, str) and normalize_bind_host(raw_host) != raw_host.strip():
            try:
                save_config(path, cfg)
            except OSError:
                pass
        return cfg


def resolve_paths(cfg: AppConfig) -> AppConfig:
    """Resolve relative paths against project root (portable installs)."""
    cfg.host = normalize_bind_host(cfg.host)

    for field in (
        "data_dir",
        "library_root",
        "music_library_root",
        "ffmpeg_path",
        "ytdlp_path",
        "ytdlp_cookies_path",
    ):
        raw = (getattr(cfg, field) or "").strip()
        if not raw:
            continue
        if field == "ytdlp_path" and raw in {"yt-dlp", "yt_dlp"}:
            continue
        p = Path(raw)
        if not p.is_absolute():
            setattr(cfg, field, str((ROOT_DIR / p).resolve()))

    # data_dir must exist for logs/db — fail soft so a bad N:\ music/video root
    # cannot prevent the tray app from starting at all.
    try:
        Path(cfg.data_dir).mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    for field in ("library_root", "music_library_root"):
        try:
            Path(getattr(cfg, field)).mkdir(parents=True, exist_ok=True)
        except OSError:
            # Drive missing / offline (e.g. N:\ not mapped yet) — continue; downloads
            # will surface a clear error later.
            pass
    return cfg


def save_config(path: Path, cfg: AppConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(cfg.model_dump(), f, sort_keys=False)


_runtime_config: AppConfig | None = None
# Bind used when uvicorn started — Settings can change host/port on disk without
# rebinding until the process fully quits and restarts.
_listen_host: str | None = None
_listen_port: int | None = None


def config_file_path() -> Path:
    """Absolute path to the config.yaml this process reads/writes."""
    path = Path(Settings().config_path)
    if not path.is_absolute():
        path = ROOT_DIR / path
    return path.resolve()


def record_listen_bind(host: str, port: int) -> None:
    """Call once when the HTTP server starts (not when Settings saves)."""
    global _listen_host, _listen_port
    _listen_host = (host or "").strip() or "0.0.0.0"
    _listen_port = int(port)


def get_listen_bind() -> tuple[str, int] | None:
    if _listen_host is None or _listen_port is None:
        return None
    return _listen_host, _listen_port


def restart_required_for_bind(cfg: AppConfig | None = None) -> bool:
    """True when saved host/port differ from the socket this process opened."""
    cfg = cfg or get_config()
    bind = get_listen_bind()
    if bind is None:
        return False
    listen_host, listen_port = bind
    return (cfg.host or "").strip() != listen_host or int(cfg.port) != int(listen_port)


def get_config() -> AppConfig:
    global _runtime_config
    if _runtime_config is None:
        _runtime_config = Settings().load()
    return _runtime_config


def set_config(cfg: AppConfig) -> AppConfig:
    global _runtime_config
    cfg = resolve_paths(cfg)
    _runtime_config = cfg
    save_config(config_file_path(), cfg)
    return cfg


def generate_api_key() -> str:
    """32-char hex key (same shape as Sonarr/Radarr)."""
    return secrets.token_hex(16)


def ensure_api_key(cfg: AppConfig | None = None) -> AppConfig:
    """Persist a new API key when missing (first run / upgraded configs)."""
    cfg = cfg or get_config()
    if (cfg.api_key or "").strip():
        return cfg
    cfg.api_key = generate_api_key()
    return set_config(cfg)


def ensure_auth_credentials(cfg: AppConfig | None = None) -> AppConfig:
    """Ensure Forms auth exists — seed from the user's other *arr credentials once."""
    from .auth import hash_password

    cfg = ensure_api_key(cfg or get_config())
    changed = False
    method = (cfg.authentication_method or "").strip().lower() or "forms"
    if method not in {"none", "forms"}:
        method = "forms"
        cfg.authentication_method = method
        changed = True
    else:
        cfg.authentication_method = method

    if not (cfg.username or "").strip():
        cfg.username = "machineshop44"
        changed = True
    if not (cfg.password_hash or "").strip():
        # Same credentials as Sonarr/Radarr/Lidarr/Readarr on the home stack
        cfg.password_hash = hash_password("Winter123")
        changed = True
    if changed:
        return set_config(cfg)
    return cfg


def regenerate_api_key() -> AppConfig:
    cfg = get_config()
    cfg.api_key = generate_api_key()
    return set_config(cfg)


def database_url() -> str:
    cfg = get_config()
    db_path = Path(cfg.data_dir) / "ytarr.db"
    return f"sqlite:///{db_path.as_posix()}"
