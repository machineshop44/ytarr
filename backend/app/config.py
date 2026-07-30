from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


DEFAULT_OUTPUT_TEMPLATE = (
    "%(uploader,playlist_title|Unknown)s/"
    "%(upload_date>%Y-%m-%d)s - %(title).200B [%(id)s].%(ext)s"
)
DEFAULT_MUSIC_OUTPUT_TEMPLATE = (
    "%(uploader,artist|Unknown)s/%(title).200B.%(ext)s"
)

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = ROOT_DIR / "config.yaml"
DEFAULT_DATA_DIR = ROOT_DIR / "data"
DEFAULT_LIBRARY_DIR = ROOT_DIR / "library"
DEFAULT_MUSIC_LIBRARY_DIR = ROOT_DIR / "music"


class PathMapping(BaseModel):
    """Sonarr-style remote path mapping: host path ↔ path Plex (or another machine) sees."""

    host_path: str = ""
    plex_path: str = ""


class AppConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8199
    data_dir: str = str(DEFAULT_DATA_DIR)
    library_root: str = str(DEFAULT_LIBRARY_DIR)
    music_library_root: str = str(DEFAULT_MUSIC_LIBRARY_DIR)
    ytdlp_path: str = "yt-dlp"
    # Empty = auto-detect bundled tools/ffmpeg, then PATH
    ffmpeg_path: str = ""
    # Named preset: best | 2160p | 1080p | 720p | 480p | worst | custom
    default_quality: str = "best"
    # Used when default_quality (or source quality) is "custom"
    format: str = "bv*+ba/b"
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
    # Sonarr-style API key for mobile hubs / remote clients (X-Api-Key)
    api_key: str = ""
    # When True, /api/* requires X-Api-Key or ?apikey= (ignored when Forms session is valid)
    api_auth_required: bool = True
    # none | forms — Forms matches Sonarr username/password login for the UI
    authentication_method: str = "forms"
    username: str = ""
    # pbkdf2_sha256$rounds$salt$hash — never store plaintext
    password_hash: str = ""


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
        cfg = AppConfig(**data)
        return resolve_paths(cfg)


def resolve_paths(cfg: AppConfig) -> AppConfig:
    """Resolve relative paths against project root (portable installs)."""
    for field in ("data_dir", "library_root", "music_library_root", "ffmpeg_path", "ytdlp_path"):
        raw = (getattr(cfg, field) or "").strip()
        if not raw:
            continue
        if field == "ytdlp_path" and raw in {"yt-dlp", "yt_dlp"}:
            continue
        p = Path(raw)
        if not p.is_absolute():
            setattr(cfg, field, str((ROOT_DIR / p).resolve()))
    Path(cfg.data_dir).mkdir(parents=True, exist_ok=True)
    Path(cfg.library_root).mkdir(parents=True, exist_ok=True)
    Path(cfg.music_library_root).mkdir(parents=True, exist_ok=True)
    return cfg


def save_config(path: Path, cfg: AppConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(cfg.model_dump(), f, sort_keys=False)


_runtime_config: AppConfig | None = None


def get_config() -> AppConfig:
    global _runtime_config
    if _runtime_config is None:
        _runtime_config = Settings().load()
    return _runtime_config


def set_config(cfg: AppConfig) -> AppConfig:
    global _runtime_config
    _runtime_config = cfg
    save_config(Path(Settings().config_path), cfg)
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
