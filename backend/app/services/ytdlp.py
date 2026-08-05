from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse
from urllib.request import urlopen

from ..config import get_config


PROGRESS_RE = re.compile(
    r"\[download\]\s+(?P<pct>\d+(?:\.\d+)?)%"
)

_which_cache: dict[str, str | None] = {}
_FFMPEG_UNSET = object()
_ffmpeg_resolved: Any = _FFMPEG_UNSET
_js_runtime_cached: list[str] | None = None
_ssl_ctx: Any = None
_ssl_ctx_nocheck: Any = None
_ssl_ctx_key: bool | None = None


def _which(cmd: str) -> str | None:
    if cmd not in _which_cache:
        _which_cache[cmd] = shutil.which(cmd)
    return _which_cache[cmd]


class YtDlpError(RuntimeError):
    pass


@dataclass
class PlaylistEntry:
    video_id: str
    title: str
    published_at: datetime | None = None
    duration: int | None = None
    thumbnail_url: str | None = None
    url: str | None = None


# yt-dlp availability values we cannot download without special auth/cookies
_BLOCKED_AVAILABILITY = {
    "subscriber_only",
    "premium",
    "needs_premium",
    "needs_auth",
    "private",
    "unavailable",
}

_MEMBERS_TITLE_RE = re.compile(
    r"(\bmembers?\s*[-–—]?\s*only\b|\bmember(?:s)?\s+exclusive\b|\[members?\]|\(members?\s*only\))",
    re.I,
)


def _is_undownloadable(item: dict[str, Any]) -> bool:
    """True for members-only / premium / private entries we should hide."""
    availability = str(item.get("availability") or "").strip().lower()
    if availability in _BLOCKED_AVAILABILITY:
        return True
    title = str(item.get("title") or "")
    if _MEMBERS_TITLE_RE.search(title):
        return True
    # Some flat dumps put badges in a list of strings / dicts
    badges = item.get("badges") or item.get("availability_badges") or []
    if isinstance(badges, list):
        blob = " ".join(str(b) for b in badges).lower()
        if "member" in blob or "premium" in blob or "subscriber" in blob:
            return True
    return False


@dataclass
class SourceInfo:
    title: str
    yt_id: str | None
    source_type: str
    folder_name: str
    thumbnail_url: str | None = None
    banner_url: str | None = None
    webpage_url: str | None = None


def _ssl_env() -> dict[str, str]:
    """Subprocess env for yt-dlp.

    On Windows, leave CA paths alone so Python/OpenSSL use the **Windows
    certificate store** (includes VPN roots like Surfshark). Forcing certifi
    here breaks those. Linux/macOS can optionally use certifi if unset.
    """
    import os

    env = os.environ.copy()
    if sys.platform.startswith("win"):
        # Prefer system store — do not override with certifi
        return env
    try:
        import certifi

        ca = certifi.where()
        env.setdefault("SSL_CERT_FILE", ca)
        env.setdefault("REQUESTS_CA_BUNDLE", ca)
        env.setdefault("CURL_CA_BUNDLE", ca)
    except Exception:
        pass
    return env


def _ytdlp_cmd() -> list[str]:
    """Resolve how to invoke yt-dlp.

    Default (empty / "yt-dlp" / "yt_dlp"): prefer a managed ``tools/yt-dlp``
    binary (auto-updated), else the bundled pip module via ``-m yt_dlp``.
    Existing paths override for advanced setups.
    """
    cfg = get_config()
    configured = (cfg.ytdlp_path or "").strip()

    # Bundled / managed — default for portable installs
    if not configured or configured in {"yt-dlp", "yt_dlp"}:
        try:
            from .ytdlp_update import managed_ytdlp_path

            managed = managed_ytdlp_path()
            if managed.exists():
                return [str(managed)]
        except Exception:
            pass
        # Frozen: re-invoke this exe with -m yt_dlp (tray_app dispatches to yt-dlp).
        # Never pass a .py launcher path — PyInstaller would start another tray instance.
        if getattr(sys, "frozen", False):
            return [sys.executable, "-m", "yt_dlp"]
        if sys.platform.startswith("win"):
            launcher = Path(__file__).resolve().parents[2] / "ytdlp_launch.py"
            if launcher.exists():
                return [sys.executable, str(launcher)]
        return [sys.executable, "-m", "yt_dlp"]

    path = Path(configured)
    if path.exists():
        return [str(path)]

    found = _which(configured)
    if found:
        return [found]

    if " " in configured:
        return configured.split()

    return [configured]


def _bundled_ffmpeg() -> Path | None:
    """Prefer ffmpeg shipped inside the ytarr app folder."""
    from ..config import ROOT_DIR

    win = sys.platform.startswith("win")
    name = "ffmpeg.exe" if win else "ffmpeg"
    for rel in (
        Path("tools") / "ffmpeg" / name,
        Path("tools") / name,
        Path("bin") / "ffmpeg" / name,
        Path("bin") / name,
    ):
        candidate = ROOT_DIR / rel
        if candidate.exists():
            return candidate
    return None


def _ffmpeg_candidates() -> list[Path]:
    """Fallback locations outside the app (legacy / optional)."""
    home = Path.home()
    desktop = home / "Desktop"
    local = Path(os.environ.get("LOCALAPPDATA", "")) if os.environ.get("LOCALAPPDATA") else None
    return [
        desktop / "ytdlp" / "ffmpeg.exe",
        desktop / "yt-dlp" / "ffmpeg.exe",
        *(
            [
                local / "Programs" / "yt-dlp" / "ffmpeg.exe",
            ]
            if local
            else []
        ),
    ]


def resolve_ffmpeg() -> Path | None:
    """Return path to ffmpeg binary, preferring the app's tools/ folder."""
    global _ffmpeg_resolved
    if _ffmpeg_resolved is not _FFMPEG_UNSET:
        return _ffmpeg_resolved  # type: ignore[return-value]

    cfg = get_config()
    configured = (cfg.ffmpeg_path or "").strip()
    found: Path | None = None
    if configured:
        p = Path(configured)
        if not p.is_absolute():
            from ..config import ROOT_DIR

            p = ROOT_DIR / p
        if p.is_dir():
            exe = p / ("ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg")
            if exe.exists():
                found = exe
        elif p.exists():
            found = p

    if found is None:
        bundled = _bundled_ffmpeg()
        if bundled:
            found = bundled

    if found is None:
        which = _which("ffmpeg")
        if which:
            found = Path(which)

    if found is None:
        for candidate in _ffmpeg_candidates():
            if candidate.exists():
                found = candidate
                break

    _ffmpeg_resolved = found
    return found


def _ffmpeg_available() -> bool:
    return resolve_ffmpeg() is not None


def _ffmpeg_location_args() -> list[str]:
    """Tell yt-dlp where ffmpeg lives (directory containing the binary)."""
    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        return []
    # yt-dlp --ffmpeg-location accepts the binary or its directory
    return ["--ffmpeg-location", str(ffmpeg.parent if ffmpeg.name.lower().startswith("ffmpeg") else ffmpeg)]


def _js_runtime_args() -> list[str]:
    """YouTube extraction increasingly needs a JS runtime (Node or Deno)."""
    global _js_runtime_cached
    if _js_runtime_cached is not None:
        return list(_js_runtime_cached)
    if _which("node"):
        _js_runtime_cached = ["--js-runtimes", "node"]
    elif _which("deno"):
        _js_runtime_cached = ["--js-runtimes", "deno"]
    else:
        _js_runtime_cached = []
    return list(_js_runtime_cached)


def _resolve_format(format_selector: str) -> tuple[str, bool]:
    """Return (format, needs_merge).

    ``bv*+ba`` requires ffmpeg to merge. Without ffmpeg, fall back to a
    single progressive stream so downloads still succeed.
    """
    fmt = (format_selector or "bv*+ba/b").strip() or "bv*+ba/b"
    needs_merge = "+" in fmt
    if needs_merge and not _ffmpeg_available():
        return "b", False
    return fmt, needs_merge


def _subprocess_hide_kwargs() -> dict[str, Any]:
    """Keep yt-dlp/ffmpeg from flashing console windows on Windows tray builds."""
    if not sys.platform.startswith("win"):
        return {}
    # CREATE_NO_WINDOW (0x08000000) — no console for the child process
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    return {"creationflags": flags}


def _common_prefix_args() -> list[str]:
    cfg = get_config()
    prefix: list[str] = []
    if cfg.nocheck_certificates:
        prefix.append("--no-check-certificates")
    prefix.extend(_js_runtime_args())
    prefix.extend(_ffmpeg_location_args())
    return prefix


def _run(
    args: list[str],
    *,
    timeout: int | None = 120,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    cmd = [*_ytdlp_cmd(), *_common_prefix_args(), *args]
    try:
        return subprocess.run(
            cmd,
            check=False,
            capture_output=capture,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            env=_ssl_env(),
            **_subprocess_hide_kwargs(),
        )
    except FileNotFoundError as exc:
        raise YtDlpError(
            f"yt-dlp not found ({' '.join(_ytdlp_cmd())}). "
            "Install backend requirements (pip install -r backend/requirements.txt) "
            "or set an absolute ytdlp_path in settings."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise YtDlpError(f"yt-dlp timed out: {' '.join(cmd)}") from exc


# UI polls /dashboard every few seconds — do not spawn yt-dlp each time.
_VERSION_TTL_SEC = 600.0
_version_cache: tuple[float, tuple[bool, str | None, str | None]] | None = None


def invalidate_version_cache() -> None:
    global _version_cache
    _version_cache = None


def get_version(*, force: bool = False) -> tuple[bool, str | None, str | None]:
    global _version_cache
    now = time.monotonic()
    if (
        not force
        and _version_cache is not None
        and now - _version_cache[0] < _VERSION_TTL_SEC
    ):
        return _version_cache[1]
    try:
        result = _run(["--version"], timeout=30)
    except YtDlpError as exc:
        out = (False, None, str(exc))
        _version_cache = (now, out)
        return out
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "unknown error").strip()
        out = (False, None, err)
        _version_cache = (now, out)
        return out
    version = (result.stdout or "").strip().splitlines()[0] if result.stdout else None
    out = (True, version, None)
    _version_cache = (now, out)
    return out


def _safe_folder_name(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:180] or "Unknown"


def _parse_upload_date(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value)
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(text.replace("+00:00", "Z"), fmt.replace("%z", "Z") if "Z" in text else fmt)
        except ValueError:
            continue
    try:
        ts = int(value)
        return datetime.utcfromtimestamp(ts)
    except (TypeError, ValueError, OSError):
        return None


def _pick_best_thumbnail(thumbnails: list[dict[str, Any]] | None) -> str | None:
    if not thumbnails:
        return None
    ranked = sorted(
        (t for t in thumbnails if t.get("url")),
        key=lambda t: (t.get("height") or 0) * (t.get("width") or 0),
        reverse=True,
    )
    return ranked[0]["url"] if ranked else None


def _pick_channel_poster(thumbnails: list[dict[str, Any]] | None) -> str | None:
    cands = _channel_poster_candidates(thumbnails)
    return cands[0] if cands else None


def _channel_poster_candidates(
    thumbnails: list[dict[str, Any]] | None,
    entries: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Ordered avatar / square / video-thumb URLs to try for a channel poster."""
    urls: list[str] = []
    seen: set[str] = set()

    def add(url: object) -> None:
        u = str(url or "").strip()
        if not u or u in seen:
            return
        seen.add(u)
        urls.append(u)

    usable = [t for t in (thumbnails or []) if t.get("url")]
    # Prefer already-sized square avatars (more reliable than avatar_uncropped =s0)
    squares = [
        t
        for t in usable
        if int(t.get("width") or 0) > 0
        and int(t.get("height") or 0) > 0
        and 0.8 <= (int(t["width"]) / int(t["height"])) <= 1.25
    ]
    for t in sorted(
        squares,
        key=lambda x: int(x.get("width") or 0) * int(x.get("height") or 0),
        reverse=True,
    ):
        add(t["url"])
    for t in usable:
        tid = str(t.get("id") or "").lower()
        if tid == "avatar_uncropped" or "avatar" in tid:
            add(t["url"])
    for t in usable:
        tid = str(t.get("id") or "").lower()
        if "banner" in tid:
            continue
        add(t["url"])

    for item in entries or []:
        add(item.get("thumbnail") or _pick_best_thumbnail(item.get("thumbnails")))
        vid = str(item.get("id") or "").strip()
        if vid and not vid.startswith("http") and len(vid) >= 6:
            add(f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg")
            add(f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg")

    return urls


def _normalize_yt_image_url(url: str) -> str:
    """yt3.googleusercontent.com bare / =s0 URLs often 400; request a concrete size."""
    u = (url or "").strip()
    if not u:
        return u
    host_ok = "googleusercontent.com" in u or "ytimg.com" in u
    if not host_ok:
        return u
    if u.endswith("=s0"):
        return u[:-3] + "=s900-c-k-c0x00ffffff-no-rj"
    # Path segment with no size query (common for channel banners/avatars)
    leaf = u.rsplit("/", 1)[-1]
    if leaf and "=" not in leaf and "?" not in leaf:
        return u + "=s900-c-k-c0x00ffffff-no-rj"
    return u


def _looks_like_image(data: bytes) -> bool:
    if not data or len(data) < 12:
        return False
    if data[:3] == b"\xff\xd8\xff":
        return True
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return True
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return True
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    return False


def image_file_ok(path: Path) -> bool:
    """True if path exists and starts with a known image magic header."""
    try:
        if not path.is_file():
            return False
        with path.open("rb") as fh:
            return _looks_like_image(fh.read(16))
    except OSError:
        return False


def _image_ssl_context():
    """Reuse one SSL context across poster downloads."""
    global _ssl_ctx, _ssl_ctx_nocheck, _ssl_ctx_key
    import ssl

    cfg = get_config()
    nocheck = bool(cfg.nocheck_certificates)
    if _ssl_ctx_key is not None and _ssl_ctx_key == nocheck:
        return _ssl_ctx_nocheck if nocheck else _ssl_ctx

    if nocheck:
        _ssl_ctx_nocheck = ssl._create_unverified_context()
        _ssl_ctx_key = True
        return _ssl_ctx_nocheck

    ctx = ssl.create_default_context()
    if sys.platform.startswith("win"):
        try:
            import truststore

            ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        except Exception:
            pass
    else:
        try:
            import certifi

            ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            pass
    _ssl_ctx = ctx
    _ssl_ctx_key = False
    return ctx

def classify_url(url: str) -> str:
    """Return 'video', 'playlist', or 'channel' from a YouTube URL shape."""
    parsed = urlparse(url.strip())
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").lower()
    query = (parsed.query or "").lower()

    if "youtu.be" in host and path.strip("/"):
        return "video"
    if "watch" in path or "v=" in query or "/shorts/" in path or "/live/" in path:
        # playlist link that also has v= is still often a playlist intent if list= present
        if "list=" in query and "watch" in path:
            # Prefer playlist when list= is present unless user wants the single video —
            # callers decide mode; classification stays 'playlist' when list= dominates.
            return "playlist"
        return "video"
    if "playlist" in path or "list=" in query:
        return "playlist"
    if "/channel/" in path or "/@" in path or "/c/" in path or "/user/" in path:
        return "channel"
    return "channel"


def _guess_source_type(url: str, info: dict[str, Any]) -> str:
    url_kind = classify_url(url)
    # Handle URLs win over extractor quirks (@channel often comes back as youtube:tab playlist)
    if url_kind == "channel":
        return "channel"
    if url_kind == "video" and info.get("_type") in {None, "video"}:
        return "video"
    extractor = (info.get("extractor_key") or info.get("extractor") or "").lower()
    path = urlparse(url).path.lower()
    if url_kind == "playlist" or "playlist" in path or extractor.endswith("playlist"):
        return "playlist"
    if info.get("_type") == "playlist" and url_kind != "video":
        return "playlist"
    if info.get("_type") == "video":
        return "video"
    return url_kind


def resolve_source(url: str) -> SourceInfo:
    result = _run(
        [
            "--dump-single-json",
            "--flat-playlist",
            "--playlist-end",
            "1",
            "--no-download",
            url,
        ],
        timeout=180,
    )
    if result.returncode != 0:
        raise YtDlpError((result.stderr or result.stdout or "Failed to resolve source").strip())

    info = json.loads(result.stdout)
    source_type = _guess_source_type(url, info)

    if source_type == "video":
        title = str(info.get("title") or "Untitled")
        folder = _safe_folder_name(
            str(info.get("channel") or info.get("uploader") or "YouTube Videos")
        )
        yt_id = info.get("id")
        thumb = info.get("thumbnail") or _pick_best_thumbnail(info.get("thumbnails"))
    elif source_type == "playlist":
        # Keep playlist identity — do not collapse to the owning channel's id/title
        title = (
            info.get("playlist_title")
            or info.get("title")
            or info.get("channel")
            or info.get("uploader")
            or "Unknown"
        )
        yt_id = info.get("playlist_id") or info.get("id")
        folder = _safe_folder_name(str(title))
        thumb = info.get("thumbnail") or _pick_best_thumbnail(info.get("thumbnails"))
    else:
        title = (
            info.get("channel")
            or info.get("uploader")
            or info.get("playlist_title")
            or info.get("title")
            or "Unknown"
        )
        yt_id = (
            info.get("channel_id")
            or info.get("uploader_id")
            or info.get("id")
        )
        folder = _safe_folder_name(str(title))
        # Prefer avatar over banner — banner URLs from yt-dlp often fail to download
        thumb = _pick_channel_poster(info.get("thumbnails")) or info.get("thumbnail")

    banner = None
    thumbnails = info.get("thumbnails") or []
    for t in thumbnails:
        url_t = t.get("url") or ""
        tid = str(t.get("id") or "").lower()
        if "banner" in url_t or "banner" in tid:
            banner = url_t
            break

    return SourceInfo(
        title=str(title),
        yt_id=str(yt_id) if yt_id else None,
        source_type=source_type,
        folder_name=folder,
        thumbnail_url=str(thumb) if thumb else None,
        banner_url=str(banner) if banner else None,
        webpage_url=info.get("webpage_url") or url,
    )


@dataclass
class SearchHit:
    kind: str  # channel | playlist | video
    title: str
    url: str
    id: str | None = None
    channel: str | None = None
    thumbnail_url: str | None = None
    duration: int | None = None
    description: str | None = None
    video_count: int | None = None


def search_youtube(
    query: str,
    *,
    kind: str = "channel",
    limit: int = 12,
) -> list[SearchHit]:
    """Search YouTube via yt-dlp (Sonarr/TVDB-style lookup)."""
    q = query.strip()
    if not q:
        return []
    # Normalize common "Artist - Song" punctuation so ytsearch matches better
    q = re.sub(r"\s*[–—]\s*", " - ", q)
    q = re.sub(r"\s{2,}", " ", q).strip()
    kind = kind.strip().lower()
    if kind not in {"channel", "playlist", "video"}:
        raise YtDlpError("kind must be channel, playlist, or video")
    limit = max(1, min(int(limit), 25))

    # YouTube results filters (sp): channels / playlists / videos
    from urllib.parse import quote_plus

    encoded = quote_plus(q)
    if kind == "channel":
        search_url = f"https://www.youtube.com/results?search_query={encoded}&sp=EgIQAg%253D%253D"
    elif kind == "playlist":
        search_url = f"https://www.youtube.com/results?search_query={encoded}&sp=EgIQAw%253D%253D"
    else:
        # ytsearchN is more reliable for videos than the results page scrape
        search_url = f"ytsearch{limit}:{q}"

    args = ["--flat-playlist", "--dump-json", "--no-download", "--playlist-end", str(limit), search_url]
    result = _run(args, timeout=180)
    if result.returncode != 0:
        raise YtDlpError((result.stderr or result.stdout or "YouTube search failed").strip())

    hits: list[SearchHit] = []
    seen_ids: set[str] = set()
    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("_type") == "playlist" and kind == "video":
            continue

        item_id = item.get("id") or item.get("url")
        title = str(item.get("title") or item.get("fulltitle") or "Untitled")
        channel = item.get("channel") or item.get("uploader") or item.get("playlist_channel")

        # Build a usable URL
        url = item.get("url") or item.get("webpage_url") or item.get("original_url")
        if not url and item_id:
            if kind == "channel" or item.get("_type") == "channel" or str(item_id).startswith("UC"):
                url = f"https://www.youtube.com/channel/{item_id}"
            elif kind == "playlist" or item.get("_type") == "playlist":
                url = f"https://www.youtube.com/playlist?list={item_id}"
            else:
                url = f"https://www.youtube.com/watch?v={item_id}"
        if not url:
            continue

        # Normalize relative youtube URLs
        if isinstance(url, str) and url.startswith("/"):
            url = "https://www.youtube.com" + url

        hit_kind = kind
        extractor = (item.get("extractor_key") or item.get("ie_key") or "").lower()
        if "channel" in extractor or str(item_id).startswith("UC"):
            hit_kind = "channel"
        elif "playlist" in extractor or (isinstance(item_id, str) and item_id.startswith("PL")):
            hit_kind = "playlist"
        elif kind == "video":
            hit_kind = "video"

        # Skip channel/playlist shells when the user asked for videos
        if kind == "video" and hit_kind != "video":
            continue

        dedupe_key = str(item_id or url)
        if dedupe_key in seen_ids:
            continue
        seen_ids.add(dedupe_key)

        video_count = None
        if hit_kind == "playlist":
            for field in ("playlist_count", "n_entries"):
                raw = item.get(field)
                if isinstance(raw, int):
                    video_count = raw
                    break

        # Prefer maxres / hq thumb for videos when flat-playlist only has tiny ones
        thumb = item.get("thumbnail") or _pick_best_thumbnail(item.get("thumbnails"))
        if not thumb and hit_kind == "video" and item_id and len(str(item_id)) == 11:
            thumb = f"https://i.ytimg.com/vi/{item_id}/hqdefault.jpg"

        hits.append(
            SearchHit(
                kind=hit_kind,
                title=title,
                url=str(url),
                id=str(item_id) if item_id else None,
                channel=str(channel) if channel else None,
                thumbnail_url=thumb,
                duration=int(item["duration"]) if item.get("duration") else None,
                description=(str(item.get("description"))[:240] if item.get("description") else None),
                video_count=video_count,
            )
        )
        if len(hits) >= limit:
            break
    return hits


def channel_topic_tags(channel_url: str) -> list[str]:
    """Pull tags/categories from a channel (and a few recent uploads) via yt-dlp."""
    result = _run(
        [
            "--dump-single-json",
            "--flat-playlist",
            "--playlist-end",
            "8",
            "--no-download",
            channel_url,
        ],
        timeout=90,
    )
    if result.returncode != 0 or not result.stdout:
        return []
    try:
        info = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    raw: list[str] = []
    for key in ("tags", "categories"):
        val = info.get(key)
        if isinstance(val, list):
            raw.extend(str(x) for x in val if x)
    for entry in info.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        for key in ("tags", "categories"):
            val = entry.get(key)
            if isinstance(val, list):
                raw.extend(str(x) for x in val if x)

    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = re.sub(r"\s+", " ", str(item).strip())
        if len(text) < 3 or len(text) > 48:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out[:12]


def _channel_playlists_url(channel_url: str) -> str:
    """Normalize a channel URL to its /playlists tab."""
    raw = channel_url.strip().rstrip("/")
    parsed = urlparse(raw)
    path = parsed.path or ""
    # Already on playlists
    if path.lower().endswith("/playlists"):
        return raw
    # Strip common tabs
    for suffix in ("/videos", "/streams", "/shorts", "/community", "/featured", "/about"):
        if path.lower().endswith(suffix):
            path = path[: -len(suffix)]
            break
    if not path or path == "/":
        raise YtDlpError("Not a channel URL")
    return f"{parsed.scheme or 'https'}://{parsed.netloc}{path}/playlists"


def _ydl_fetch_html(url: str) -> str:
    """Fetch a YouTube page using yt-dlp's downloader (same SSL path as downloads)."""
    cfg = get_config()
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": bool(cfg.nocheck_certificates),
    }
    try:
        from yt_dlp.networking.common import Request
        from yt_dlp.YoutubeDL import YoutubeDL
    except ImportError as exc:
        raise YtDlpError("yt-dlp is not installed") from exc

    # Windows: trust OS/VPN roots (Surfshark, etc.)
    if sys.platform.startswith("win"):
        try:
            import truststore

            truststore.inject_into_ssl()
        except Exception:
            pass

    with YoutubeDL(opts) as ydl:
        resp = ydl.urlopen(Request(url, headers={"Accept-Language": "en-US,en"}))
        return resp.read().decode("utf-8", "replace")


def _parse_video_count_text(text: str) -> int | None:
    m = re.search(r"([\d,]+)\s+videos?", text, re.I)
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _playlist_counts_from_channel_html(html: str) -> dict[str, int]:
    """Map playlist id -> video count from channel /playlists page badges."""
    m = re.search(r"ytInitialData\s*=\s*(\{.+?\})\s*;", html, re.S)
    if not m:
        return {}
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}

    counts: dict[str, int] = {}

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            lv = obj.get("lockupViewModel")
            if isinstance(lv, dict) and lv.get("contentType") == "LOCKUP_CONTENT_TYPE_PLAYLIST":
                pid = lv.get("contentId")
                if not isinstance(pid, str):
                    blob = json.dumps(lv)
                    pm = re.search(r'"playlistId"\s*:\s*"(PL[^"]+)"', blob)
                    pid = pm.group(1) if pm else None
                if isinstance(pid, str):
                    cm = re.search(r'"text"\s*:\s*"(\d[\d,]*)\s+videos?"', json.dumps(lv))
                    if cm:
                        try:
                            counts[pid] = int(cm.group(1).replace(",", ""))
                        except ValueError:
                            pass
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(data)
    return counts


def _lookup_playlist_count(counts: dict[str, int], playlist_id: str | None) -> int | None:
    if not playlist_id or not counts:
        return None
    if playlist_id in counts:
        return counts[playlist_id]
    # Match truncated / prefix forms YouTube sometimes returns
    for key, value in counts.items():
        if key.startswith(playlist_id) or playlist_id.startswith(key):
            return value
    return None


def list_channel_playlists(channel_url: str, *, limit: int = 50) -> list[SearchHit]:
    """List playlists for a channel (Lidarr album-style drill-in)."""
    playlists_url = _channel_playlists_url(channel_url)
    limit = max(1, min(int(limit), 100))
    args = [
        "--flat-playlist",
        "--dump-json",
        "--no-download",
        "--playlist-end",
        str(limit),
        playlists_url,
    ]
    result = _run(args, timeout=90)
    if result.returncode != 0:
        raise YtDlpError(
            (result.stderr or result.stdout or "Failed to list channel playlists").strip()
        )

    # Optional badge counts — do not block the add UI if this scrape is slow.
    counts: dict[str, int] = {}
    try:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(_ydl_fetch_html, playlists_url)
            html = fut.result(timeout=8)
            counts = _playlist_counts_from_channel_html(html)
    except Exception:
        counts = {}

    channel_name: str | None = None
    hits: list[SearchHit] = []
    seen: set[str] = set()
    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue

        channel_name = (
            channel_name
            or item.get("channel")
            or item.get("uploader")
            or item.get("playlist_uploader")
        )

        item_id = item.get("id") or item.get("url")
        title = str(item.get("title") or item.get("playlist_title") or "Untitled")
        # Skip the channel root / non-playlist entries
        itype = (item.get("_type") or "").lower()
        ie = (item.get("ie_key") or item.get("extractor_key") or "").lower()
        if itype == "url" and "playlist" not in ie and not str(item_id).startswith(("PL", "OL", "UU", "LL", "FL", "RD")):
            # Still allow if URL looks like playlist
            url_guess = item.get("url") or item.get("webpage_url") or ""
            if "list=" not in str(url_guess) and "/playlist" not in str(url_guess):
                continue

        url = item.get("url") or item.get("webpage_url")
        if not url and item_id:
            url = f"https://www.youtube.com/playlist?list={item_id}"
        if isinstance(url, str) and url.startswith("/"):
            url = "https://www.youtube.com" + url
        if not url:
            continue

        key = str(item_id or url)
        if key in seen:
            continue
        seen.add(key)

        pid = str(item_id) if item_id else None
        # Prefer channel-page badge counts; flat-playlist often reports page size, not length.
        video_count = _lookup_playlist_count(counts, pid)
        if video_count is None:
            for field in ("playlist_count", "n_entries"):
                raw = item.get(field)
                if isinstance(raw, int) and raw > 0:
                    video_count = raw
                    break
                if isinstance(raw, str):
                    parsed_count = _parse_video_count_text(raw)
                    if parsed_count is not None:
                        video_count = parsed_count
                        break

        hits.append(
            SearchHit(
                kind="playlist",
                title=title,
                url=str(url),
                id=pid,
                channel=str(channel_name) if channel_name else None,
                thumbnail_url=item.get("thumbnail") or _pick_best_thumbnail(item.get("thumbnails")),
                duration=None,
                description=None,
                video_count=video_count,
            )
        )
        if len(hits) >= limit:
            break
    return hits


def list_entries(url: str, *, limit: int | None = None) -> list[PlaylistEntry]:
    args = [
        "--flat-playlist",
        "--dump-json",
        "--no-download",
        url,
    ]
    if limit is not None:
        args[0:0] = ["--playlist-end", str(limit)]

    # --playlist-end must come before URL; rebuild carefully
    args = ["--flat-playlist", "--dump-json", "--no-download"]
    if limit is not None:
        args.extend(["--playlist-end", str(limit)])
    args.append(url)

    result = _run(args, timeout=300)
    if result.returncode != 0:
        raise YtDlpError((result.stderr or result.stdout or "Failed to list entries").strip())

    entries: list[PlaylistEntry] = []
    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        vid = item.get("id") or item.get("url")
        if not vid:
            continue
        # Skip non-video playlist wrappers
        if item.get("_type") == "playlist":
            continue
        if _is_undownloadable(item):
            continue
        entries.append(
            PlaylistEntry(
                video_id=str(vid),
                title=str(item.get("title") or "Untitled"),
                published_at=_parse_upload_date(
                    item.get("upload_date")
                    or item.get("release_date")
                    or item.get("timestamp")
                    or item.get("release_timestamp")
                    or item.get("epoch")
                ),
                duration=int(item["duration"]) if item.get("duration") else None,
                thumbnail_url=item.get("thumbnail") or _pick_best_thumbnail(item.get("thumbnails")),
                url=item.get("url") or item.get("webpage_url"),
            )
        )
    # Prefer newest-first when dates exist (Uploads / dated playlists)
    entries.sort(
        key=lambda e: e.published_at or datetime.min,
        reverse=True,
    )
    return entries


def download_image(url: str, dest: Path) -> Path | None:
    try:
        from urllib.request import Request, urlopen as _urlopen

        dest.parent.mkdir(parents=True, exist_ok=True)
        url = _normalize_yt_image_url(url)
        ctx = _image_ssl_context()
        req = Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                "Referer": "https://www.youtube.com/",
            },
        )
        with _urlopen(req, timeout=60, context=ctx) as resp:  # noqa: S310
            data = resp.read()
        if len(data) < 64 or not _looks_like_image(data):
            return None
        dest.write_bytes(data)
        return dest
    except Exception:
        return None


def fetch_channel_artwork(
    url: str,
    folder: Path,
) -> tuple[Path | None, Path | None]:
    """Write poster.jpg / fanart.jpg into folder using one primary yt-dlp dump."""
    folder.mkdir(parents=True, exist_ok=True)
    poster = folder / "poster.jpg"
    fanart = folder / "fanart.jpg"

    thumbs: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    banner_url: str | None = None
    try:
        result = _run(
            ["--dump-single-json", "--flat-playlist", "--playlist-end", "5", "--no-download", url],
            timeout=120,
        )
        if result.returncode == 0 and result.stdout:
            rich = json.loads(result.stdout)
            thumbs = list(rich.get("thumbnails") or [])
            entries = [e for e in (rich.get("entries") or []) if isinstance(e, dict)]
            for t in thumbs:
                u = t.get("url") or ""
                tid = str(t.get("id") or "").lower()
                if "banner" in u or "banner" in tid:
                    banner_url = u
                    break
            seed = _pick_channel_poster(thumbs) or rich.get("thumbnail")
            candidates = _channel_poster_candidates(thumbs, entries)
            if seed:
                candidates = [str(seed)] + [u for u in candidates if u != str(seed)]
        else:
            candidates = []
    except Exception:
        candidates = []

    poster_path = None
    for cand in candidates:
        poster_path = download_image(cand, poster)
        if poster_path:
            break

    # Rare fallback dump when flat listing had no usable avatar
    if not poster_path:
        try:
            result = _run(
                ["--dump-single-json", "--playlist-items", "0", "--no-download", url],
                timeout=120,
            )
            if result.returncode == 0 and result.stdout:
                rich2 = json.loads(result.stdout)
                for cand in _channel_poster_candidates(rich2.get("thumbnails"), rich2.get("entries")):
                    if cand in candidates:
                        continue
                    poster_path = download_image(cand, poster)
                    if poster_path:
                        break
                if not banner_url:
                    for t in rich2.get("thumbnails") or []:
                        u = t.get("url") or ""
                        tid = str(t.get("id") or "").lower()
                        if "banner" in u or "banner" in tid:
                            banner_url = u
                            break
        except Exception:
            pass

    fanart_path = None
    if banner_url:
        fanart_path = download_image(str(banner_url), fanart)
    if not fanart_path and poster_path and poster_path.exists() and not fanart.exists():
        shutil.copy2(poster_path, fanart)
        fanart_path = fanart

    return poster_path, fanart_path


_SPONSORBLOCK_ALLOWED = frozenset(
    {
        "sponsor",
        "intro",
        "outro",
        "selfpromo",
        "preview",
        "filler",
        "interaction",
        "music_offtopic",
        "hook",
        "all",
        "default",
    }
)


def _normalize_sponsorblock_categories(raw: str | None) -> str | None:
    """Return a sanitized comma list, or None when empty/disabled."""
    if not raw or not str(raw).strip():
        return None
    parts: list[str] = []
    for token in str(raw).replace(" ", "").split(","):
        if not token:
            continue
        # Allow yt-dlp exclusion syntax: -filler
        key = token[1:] if token.startswith("-") else token
        if key.lower() not in _SPONSORBLOCK_ALLOWED:
            continue
        parts.append(token.lower() if not token.startswith("-") else f"-{key.lower()}")
    return ",".join(parts) if parts else None


def download_video(
    video_url: str,
    *,
    library_root: Path,
    output_template: str,
    format_selector: str,
    progress_cb: Callable[[float], None] | None = None,
    extract_audio: bool = False,
    audio_quality: str = "0",
    sponsorblock_categories: str | None = None,
) -> Path | None:
    library_root.mkdir(parents=True, exist_ok=True)
    # Keep template separators as yt-dlp expects (/); don't let Path flip them on Windows
    outtmpl = str(library_root).rstrip("\\/") + "/" + output_template.lstrip("/\\")
    sb_cats = _normalize_sponsorblock_categories(sponsorblock_categories)
    if extract_audio and not _ffmpeg_available():
        raise YtDlpError(
            "ffmpeg is required for Music (audio) downloads. "
            "Install tools/ffmpeg (scripts\\fetch-ffmpeg.ps1) or set ffmpeg_path in Settings."
        )
    if sb_cats and not _ffmpeg_available():
        raise YtDlpError(
            "ffmpeg is required to cut SponsorBlock segments. "
            "Install tools/ffmpeg or disable SponsorBlock remove in Settings."
        )
    fmt, needs_merge = _resolve_format(format_selector)
    args = [
        *_common_prefix_args(),
        "--newline",
        "--retries",
        "10",
        "--fragment-retries",
        "10",
        "-f",
        fmt,
        "-o",
        outtmpl,
        "--print",
        "after_move:filepath",
        "--print",
        "filepath",
        video_url,
    ]
    if sys.platform.startswith("win"):
        args[0:0] = ["--windows-filenames"]
    if extract_audio:
        aq = (audio_quality or "0").strip() or "0"
        args.extend(["-x", "--audio-format", "m4a", "--audio-quality", aq])
    elif needs_merge:
        args.extend(["--merge-output-format", "mkv"])
    if sb_cats:
        args.extend(["--sponsorblock-remove", sb_cats])

    cmd = [*_ytdlp_cmd(), *args]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_ssl_env(),
            **_subprocess_hide_kwargs(),
        )
    except FileNotFoundError as exc:
        raise YtDlpError(f"yt-dlp not found ({' '.join(_ytdlp_cmd())})") from exc

    file_path: Path | None = None
    tail: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            tail.append(line)
            if len(tail) > 40:
                tail = tail[-40:]
        match = PROGRESS_RE.search(line)
        if match and progress_cb:
            try:
                progress_cb(float(match.group("pct")))
            except ValueError:
                pass
        # yt-dlp print filepath lines (absolute paths)
        if line and not line.startswith("[") and Path(line).suffix and ("/" in line or "\\" in line):
            candidate = Path(line.strip())
            if candidate.suffix.lower() in {".mkv", ".mp4", ".webm", ".m4a", ".mp3", ".opus"}:
                file_path = candidate

    code = proc.wait()
    if code != 0:
        err_lines = [
            ln
            for ln in tail
            if ln.startswith("ERROR:")
            or "ERROR:" in ln
            or ln.startswith("WARNING:")
            or "ffmpeg" in ln.lower()
        ]
        detail = " | ".join(err_lines[-4:]) if err_lines else (" | ".join(tail[-6:]) if tail else "no output")
        hint = ""
        blob = " ".join(tail).lower()
        if "ffmpeg" in blob and not _ffmpeg_available():
            hint = (
                " Install ffmpeg and ensure it is on PATH for best quality "
                "(bv*+ba merges), or keep using single-file format fallback."
            )
        if "unavailable" in blob:
            hint += " This video may be private, region-locked, or removed."
        if "javascript runtime" in blob and not _js_runtime_args():
            hint += " Install Node.js so yt-dlp can extract YouTube formats."
        raise YtDlpError(f"yt-dlp failed (exit {code}): {detail}.{hint}".strip())
    if progress_cb:
        progress_cb(100.0)
    return file_path


def video_page_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"
