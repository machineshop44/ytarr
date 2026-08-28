"""Plex Media Server Connect — Arr-style library refresh after import."""

from __future__ import annotations

import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from ..config import get_config

log = logging.getLogger("ytarr.plex")

_lock = threading.Lock()
_pending: dict[str, float] = {}  # key -> earliest fire time
_timer: threading.Timer | None = None


def _cfg_enabled() -> bool:
    cfg = get_config()
    return bool(getattr(cfg, "plex_enabled", False)) and bool(
        (getattr(cfg, "plex_url", "") or "").strip()
    ) and bool((getattr(cfg, "plex_token", "") or "").strip())


def _base_url() -> str:
    return (get_config().plex_url or "").strip().rstrip("/")


def _token() -> str:
    return (get_config().plex_token or "").strip()


def _request(
    path: str,
    *,
    params: dict[str, str] | None = None,
    method: str = "GET",
    timeout: float = 30,
) -> tuple[int, bytes]:
    q = dict(params or {})
    q["X-Plex-Token"] = _token()
    url = f"{_base_url()}{path}?{urllib.parse.urlencode(q)}"
    req = urllib.request.Request(
        url,
        method=method,
        headers={
            "Accept": "application/xml",
            "X-Plex-Client-Identifier": "ytarr",
            "X-Plex-Product": "ytarr",
            "X-Plex-Version": "1",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return int(resp.status), resp.read() or b""
    except urllib.error.HTTPError as exc:
        body = exc.read() if hasattr(exc, "read") else b""
        return int(exc.code), body or str(exc).encode()


def list_sections() -> list[dict[str, Any]]:
    """Return Plex library sections (id, title, type, locations)."""
    if not _token() or not _base_url():
        raise ValueError("Plex URL and token required")
    code, body = _request("/library/sections")
    if code >= 400:
        raise ValueError(f"Plex sections failed ({code}): {body[:200]!r}")
    root = ET.fromstring(body)
    out: list[dict[str, Any]] = []
    for el in root.findall("Directory"):
        locs = [loc.get("path") or "" for loc in el.findall("Location") if loc.get("path")]
        out.append(
            {
                "id": el.get("key") or el.get("id") or "",
                "title": el.get("title") or "Untitled",
                "type": el.get("type") or "",
                "agent": el.get("agent") or "",
                "locations": locs,
            }
        )
    return out


def test_connection() -> dict[str, Any]:
    """Verify token against /identity and list sections."""
    if not _base_url():
        return {"ok": False, "error": "Plex URL is empty"}
    if not _token():
        return {"ok": False, "error": "Plex token is empty"}
    code, body = _request("/identity")
    if code >= 400:
        return {"ok": False, "error": f"Plex identity HTTP {code}: {body[:180]!r}"}
    try:
        sections = list_sections()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    machine = ""
    try:
        root = ET.fromstring(body)
        machine = root.get("machineIdentifier") or ""
    except ET.ParseError:
        pass
    return {
        "ok": True,
        "machine_identifier": machine,
        "sections": sections,
        "section_count": len(sections),
    }


def map_host_path_to_plex(host_path: str | Path) -> str:
    """Apply path_mappings so Plex sees the path it expects."""
    cfg = get_config()
    text = str(host_path)
    best: tuple[int, str] | None = None
    for mapping in getattr(cfg, "path_mappings", None) or []:
        host = (mapping.host_path or "").strip().rstrip("\\/")
        plex = (mapping.plex_path or "").strip().rstrip("\\/")
        if not host or not plex:
            continue
        # Case-insensitive prefix match on Windows-style paths
        if text.lower().startswith(host.lower()):
            rest = text[len(host) :].lstrip("\\/")
            mapped = f"{plex}/{rest}".replace("\\", "/") if rest else plex.replace("\\", "/")
            if best is None or len(host) > best[0]:
                best = (len(host), mapped)
    if best:
        return best[1]
    return text.replace("\\", "/")


def _section_for_media(media_type: str) -> str:
    cfg = get_config()
    if (media_type or "video").lower() == "audio":
        return str(getattr(cfg, "plex_music_section_id", "") or "").strip()
    return str(getattr(cfg, "plex_video_section_id", "") or "").strip()


def refresh_section(section_id: str, *, path: str | None = None) -> dict[str, Any]:
    sid = (section_id or "").strip()
    if not sid:
        return {"ok": False, "error": "No Plex section id"}
    params: dict[str, str] = {}
    if path:
        params["path"] = path
    code, body = _request(f"/library/sections/{sid}/refresh", params=params)
    ok = code < 400
    if ok:
        log.info("Plex refresh section=%s path=%s", sid, path or "(full)")
    else:
        log.warning("Plex refresh failed section=%s code=%s body=%r", sid, code, body[:200])
    return {"ok": ok, "status": code, "section_id": sid, "path": path}


def _flush_pending() -> None:
    global _timer
    with _lock:
        _timer = None
        now = time.monotonic()
        ready = [k for k, t in _pending.items() if t <= now]
        for k in ready:
            _pending.pop(k, None)
        still = {k: t for k, t in _pending.items() if t > now}
        _pending.clear()
        _pending.update(still)
        if still:
            delay = max(0.5, min(still.values()) - now)
            _timer = threading.Timer(delay, _flush_pending)
            _timer.daemon = True
            _timer.start()
        jobs = list(ready)

    for key in jobs:
        # key = "sectionId|pathOr*"
        sid, _, path = key.partition("|")
        refresh_path = None if path == "*" else path
        try:
            refresh_section(sid, path=refresh_path)
        except Exception as exc:  # noqa: BLE001
            log.warning("Plex refresh error: %s", exc)


def schedule_refresh(
    *,
    host_file_path: str | Path | None = None,
    media_type: str = "video",
    force_section: str | None = None,
) -> None:
    """Debounced Plex refresh for a file path or whole section."""
    if not _cfg_enabled():
        return
    sid = (force_section or _section_for_media(media_type) or "").strip()
    if not sid:
        log.debug("Plex enabled but no section id for media_type=%s", media_type)
        return

    plex_path: str | None = None
    if host_file_path:
        p = Path(host_file_path)
        folder = p if p.is_dir() else p.parent
        plex_path = map_host_path_to_plex(folder)

    cfg = get_config()
    debounce = max(5, int(getattr(cfg, "plex_refresh_debounce_seconds", 45) or 45))
    key = f"{sid}|{plex_path or '*'}"
    fire_at = time.monotonic() + debounce

    global _timer
    with _lock:
        prev = _pending.get(key)
        _pending[key] = fire_at if prev is None else min(prev, fire_at)
        if _timer is None:
            _timer = threading.Timer(debounce, _flush_pending)
            _timer.daemon = True
            _timer.start()


def notify_library_changed(
    *,
    host_file_path: str | Path | None = None,
    media_type: str = "video",
) -> None:
    """Public hook: schedule Plex refresh (+ optional webhook)."""
    schedule_refresh(host_file_path=host_file_path, media_type=media_type)
    try:
        from . import notify

        notify.on_library_import(host_file_path=host_file_path, media_type=media_type)
    except Exception:
        pass
