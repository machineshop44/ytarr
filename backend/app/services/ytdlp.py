from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
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

    Default (empty / "yt-dlp" / "yt_dlp"): bundled pip module via
    ``python -m yt_dlp``. On Windows we launch through ``ytdlp_launch.py``
    so OS/VPN certificate roots (Surfshark, etc.) are trusted.
    Existing paths override for advanced setups.
    """
    cfg = get_config()
    configured = (cfg.ytdlp_path or "").strip()

    # Bundled module — default for portable installs (no external exe required)
    if not configured or configured in {"yt-dlp", "yt_dlp"}:
        if sys.platform.startswith("win"):
            launcher = Path(__file__).resolve().parents[2] / "ytdlp_launch.py"
            if launcher.exists():
                return [sys.executable, str(launcher)]
        return [sys.executable, "-m", "yt_dlp"]

    path = Path(configured)
    if path.exists():
        return [str(path)]

    found = shutil.which(configured)
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
    cfg = get_config()
    configured = (cfg.ffmpeg_path or "").strip()
    if configured:
        p = Path(configured)
        if not p.is_absolute():
            from ..config import ROOT_DIR

            p = ROOT_DIR / p
        if p.is_dir():
            exe = p / ("ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg")
            if exe.exists():
                return exe
        if p.exists():
            return p

    bundled = _bundled_ffmpeg()
    if bundled:
        return bundled

    which = shutil.which("ffmpeg")
    if which:
        return Path(which)

    for candidate in _ffmpeg_candidates():
        if candidate.exists():
            return candidate
    return None


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
    if shutil.which("node"):
        return ["--js-runtimes", "node"]
    if shutil.which("deno"):
        return ["--js-runtimes", "deno"]
    return []


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
        )
    except FileNotFoundError as exc:
        raise YtDlpError(
            f"yt-dlp not found ({' '.join(_ytdlp_cmd())}). "
            "Install backend requirements (pip install -r backend/requirements.txt) "
            "or set an absolute ytdlp_path in settings."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise YtDlpError(f"yt-dlp timed out: {' '.join(cmd)}") from exc


def get_version() -> tuple[bool, str | None, str | None]:
    try:
        result = _run(["--version"], timeout=30)
    except YtDlpError as exc:
        return False, None, str(exc)
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "unknown error").strip()
        return False, None, err
    version = (result.stdout or "").strip().splitlines()[0] if result.stdout else None
    return True, version, None


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
            or info.get("playlist_id")
            or info.get("id")
        )
        folder = _safe_folder_name(str(title))

    thumb = info.get("thumbnail") or _pick_best_thumbnail(info.get("thumbnails"))
    banner = None
    thumbnails = info.get("thumbnails") or []
    for t in thumbnails:
        url_t = t.get("url") or ""
        if "banner" in url_t or (t.get("id") or "").lower().find("banner") >= 0:
            banner = url_t
            break

    return SourceInfo(
        title=str(title),
        yt_id=str(yt_id) if yt_id else None,
        source_type=source_type,
        folder_name=folder,
        thumbnail_url=thumb,
        banner_url=banner,
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

        video_count = None
        if hit_kind == "playlist":
            for field in ("playlist_count", "n_entries"):
                raw = item.get(field)
                if isinstance(raw, int):
                    video_count = raw
                    break

        hits.append(
            SearchHit(
                kind=hit_kind,
                title=title,
                url=str(url),
                id=str(item_id) if item_id else None,
                channel=str(channel) if channel else None,
                thumbnail_url=item.get("thumbnail") or _pick_best_thumbnail(item.get("thumbnails")),
                duration=int(item["duration"]) if item.get("duration") else None,
                description=(str(item.get("description"))[:240] if item.get("description") else None),
                video_count=video_count,
            )
        )
        if len(hits) >= limit:
            break
    return hits


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
    result = _run(args, timeout=180)
    if result.returncode != 0:
        raise YtDlpError(
            (result.stderr or result.stdout or "Failed to list channel playlists").strip()
        )

    # Video counts live on the channel playlists tab badges — not in flat-playlist JSON.
    counts: dict[str, int] = {}
    try:
        counts = _playlist_counts_from_channel_html(_ydl_fetch_html(playlists_url))
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
                    item.get("upload_date") or item.get("timestamp") or item.get("release_timestamp")
                ),
                duration=int(item["duration"]) if item.get("duration") else None,
                thumbnail_url=item.get("thumbnail") or _pick_best_thumbnail(item.get("thumbnails")),
                url=item.get("url") or item.get("webpage_url"),
            )
        )
    return entries


def download_image(url: str, dest: Path) -> Path | None:
    try:
        import ssl
        from urllib.request import Request, urlopen as _urlopen

        dest.parent.mkdir(parents=True, exist_ok=True)
        cfg = get_config()
        if cfg.nocheck_certificates:
            ctx = ssl._create_unverified_context()
        else:
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
        req = Request(url, headers={"User-Agent": "ytarr/0.1"})
        with _urlopen(req, timeout=60, context=ctx) as resp:  # noqa: S310
            data = resp.read()
        if not data:
            return None
        dest.write_bytes(data)
        return dest
    except Exception:
        return None


def fetch_channel_artwork(
    url: str,
    folder: Path,
) -> tuple[Path | None, Path | None]:
    """Resolve source and write poster.jpg / fanart.jpg into folder."""
    info = resolve_source(url)
    folder.mkdir(parents=True, exist_ok=True)
    poster = folder / "poster.jpg"
    fanart = folder / "fanart.jpg"
    poster_path = download_image(info.thumbnail_url, poster) if info.thumbnail_url else None

    banner_url = info.banner_url
    if not banner_url:
        # Try a fuller dump without flat playlist for better thumbs
        try:
            result = _run(
                ["--dump-single-json", "--playlist-items", "0", "--no-download", url],
                timeout=120,
            )
            if result.returncode == 0 and result.stdout:
                rich = json.loads(result.stdout)
                thumbs = rich.get("thumbnails") or []
                for t in thumbs:
                    u = t.get("url") or ""
                    if "maxresdefault" in u or "banner" in u:
                        banner_url = u
                        break
                if not banner_url:
                    banner_url = rich.get("thumbnail") or _pick_best_thumbnail(thumbs)
        except Exception:
            banner_url = None

    fanart_path = None
    if banner_url and banner_url != info.thumbnail_url:
        fanart_path = download_image(banner_url, fanart)
    elif info.thumbnail_url and not fanart.exists():
        # Fall back: copy poster as fanart so Plex has something
        if poster_path and poster_path.exists():
            shutil.copy2(poster_path, fanart)
            fanart_path = fanart

    return poster_path, fanart_path


def download_video(
    video_url: str,
    *,
    library_root: Path,
    output_template: str,
    format_selector: str,
    progress_cb: Callable[[float], None] | None = None,
) -> Path | None:
    library_root.mkdir(parents=True, exist_ok=True)
    # Keep template separators as yt-dlp expects (/); don't let Path flip them on Windows
    outtmpl = str(library_root).rstrip("\\/") + "/" + output_template.lstrip("/\\")
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
    if needs_merge:
        args.extend(["--merge-output-format", "mkv"])

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
