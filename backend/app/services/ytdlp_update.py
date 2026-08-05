"""Keep managed yt-dlp + ffmpeg fresh (startup + ~daily).

Frozen installs cannot ``pip install -U`` into the bundle, so we maintain
``tools/yt-dlp(.exe)`` and ``tools/ffmpeg/`` next to the app.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import get_config
from ..paths import project_root

log = logging.getLogger("ytarr.ytdlp_update")

# Crash-loop guard only — scheduler still runs at startup + every 24h.
MIN_NETWORK_GAP_SEC = 15 * 60
_lock = threading.Lock()
_YTDLP_RELEASE_BASE = "https://github.com/yt-dlp/yt-dlp/releases/latest/download"
_FFMPEG_WIN_ZIP = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
    "ffmpeg-master-latest-win64-gpl-shared.zip"
)


def managed_ytdlp_path() -> Path:
    name = "yt-dlp.exe" if sys.platform.startswith("win") else "yt-dlp"
    return project_root() / "tools" / name


def managed_ffmpeg_dir() -> Path:
    return project_root() / "tools" / "ffmpeg"


def managed_ffmpeg_exe() -> Path:
    name = "ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg"
    return managed_ffmpeg_dir() / name


def _stamp_path() -> Path:
    cfg = get_config()
    return Path(cfg.data_dir) / "ytdlp-update.json"


def _read_stamp() -> dict[str, Any]:
    path = _stamp_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_stamp(**fields: Any) -> None:
    path = _stamp_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _read_stamp()
    data.update(fields)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _hide_kwargs() -> dict[str, Any]:
    if sys.platform.startswith("win"):
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {}


def _download_ytdlp_binary(dest: Path) -> None:
    import httpx

    asset = "yt-dlp.exe" if sys.platform.startswith("win") else "yt-dlp"
    url = f"{_YTDLP_RELEASE_BASE}/{asset}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, dir=str(dest.parent), suffix=".tmp") as tmp:
        tmp_path = Path(tmp.name)
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=120.0) as resp:
            resp.raise_for_status()
            with tmp_path.open("wb") as out:
                for chunk in resp.iter_bytes():
                    out.write(chunk)
        os.replace(tmp_path, dest)
        if not sys.platform.startswith("win"):
            dest.chmod(dest.stat().st_mode | 0o111)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def _self_update_ytdlp(exe: Path) -> tuple[bool, str]:
    """Run official ``yt-dlp -U``. Returns (changed_or_ok, message)."""
    try:
        proc = subprocess.run(
            [str(exe), "-U"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            env={**os.environ, "PYTHONUTF8": "1"},
            **_hide_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    if proc.returncode != 0:
        return False, out or f"exit {proc.returncode}"
    return True, out or "up to date"


def _ffmpeg_version(exe: Path) -> str | None:
    if not exe.exists():
        return None
    try:
        proc = subprocess.run(
            [str(exe), "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            **_hide_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    line = (proc.stdout or "").strip().splitlines()
    return line[0].strip() if line else "unknown"


def _download_ffmpeg(dest_dir: Path) -> str:
    """Download BtbN Windows shared build into tools/ffmpeg. Returns version string."""
    if not sys.platform.startswith("win"):
        raise RuntimeError("Automatic ffmpeg install is only supported on Windows")

    import httpx

    dest_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ytarr-ffmpeg-") as tmp_name:
        tmp = Path(tmp_name)
        zip_path = tmp / "ffmpeg.zip"
        with httpx.stream("GET", _FFMPEG_WIN_ZIP, follow_redirects=True, timeout=300.0) as resp:
            resp.raise_for_status()
            with zip_path.open("wb") as out:
                for chunk in resp.iter_bytes():
                    out.write(chunk)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp)
        found = next(tmp.rglob("ffmpeg.exe"), None)
        if not found:
            raise RuntimeError("ffmpeg.exe not found in downloaded archive")
        bin_dir = found.parent
        for name in ("ffmpeg.exe", "ffprobe.exe"):
            src = bin_dir / name
            if src.exists():
                shutil.copy2(src, dest_dir / name)
        for dll in bin_dir.glob("*.dll"):
            shutil.copy2(dll, dest_dir / dll.name)

    version = _ffmpeg_version(dest_dir / "ffmpeg.exe") or "installed"
    return version


def _ensure_ffmpeg(*, refresh: bool = True) -> dict[str, Any]:
    """Verify tools/ffmpeg works; download/refresh when missing, broken, or refresh=True."""
    exe = managed_ffmpeg_exe()
    dest = managed_ffmpeg_dir()
    result: dict[str, Any] = {"ok": False, "path": str(exe)}

    if not sys.platform.startswith("win"):
        # Prefer already-resolved ffmpeg from PATH / bundle on non-Windows
        from . import ytdlp as ytdlp_svc

        resolved = ytdlp_svc.resolve_ffmpeg()
        if resolved and resolved.exists():
            result["ok"] = True
            result["action"] = "existing"
            result["path"] = str(resolved)
            result["version"] = _ffmpeg_version(resolved)
            return result
        result["error"] = "automatic ffmpeg update is Windows-only; install ffmpeg on PATH"
        return result

    current = _ffmpeg_version(exe)
    needs_install = current is None
    if not needs_install and not refresh:
        result["ok"] = True
        result["action"] = "ok"
        result["version"] = current
        return result

    try:
        if needs_install:
            log.info("ffmpeg missing/broken — downloading to %s", dest)
            result["action"] = "downloaded"
        else:
            log.info("Refreshing ffmpeg in %s", dest)
            result["action"] = "refreshed"
        version = _download_ffmpeg(dest)
        result["ok"] = True
        result["version"] = version
        log.info("ffmpeg %s → %s", result["action"], version)
    except Exception as exc:
        result["error"] = str(exc)
        if current:
            # Keep working binary if refresh failed
            result["ok"] = True
            result["action"] = "kept-existing"
            result["version"] = current
            result["refresh_error"] = str(exc)
            log.warning("ffmpeg refresh failed (%s); keeping existing %s", exc, current)
        else:
            log.error("ffmpeg install failed: %s", exc)
    return result


def _update_ytdlp() -> dict[str, Any]:
    exe = managed_ytdlp_path()
    result: dict[str, Any] = {"ok": False, "path": str(exe)}

    if not exe.exists():
        log.info("Downloading yt-dlp to %s", exe)
        try:
            _download_ytdlp_binary(exe)
        except Exception as exc:
            result["error"] = f"download failed: {exc}"
            return result
        result["action"] = "downloaded"
    else:
        ok, msg = _self_update_ytdlp(exe)
        if not ok:
            log.warning("yt-dlp -U failed (%s); re-downloading", msg)
            try:
                _download_ytdlp_binary(exe)
                result["action"] = "redownloaded"
                result["prior_error"] = msg
            except Exception as exc:
                result["error"] = f"update failed: {msg}; redownload: {exc}"
                return result
        else:
            result["action"] = "self-updated"
            result["detail"] = msg[:500]

    try:
        from . import ytdlp as ytdlp_svc

        ytdlp_svc.invalidate_version_cache()
        ok, version, err = ytdlp_svc.get_version()
        result["ytdlp_ok"] = ok
        result["version"] = version
        if err:
            result["version_error"] = err
    except Exception as exc:
        result["version_error"] = str(exc)

    result["ok"] = True
    log.info("yt-dlp update %s version=%s", result.get("action"), result.get("version"))
    return result


def maybe_update_ytdlp(*, force: bool = False) -> dict[str, Any]:
    """Ensure managed yt-dlp and ffmpeg are present and current.

    Safe to call from the scheduler. Skips if last successful check was recent
    unless ``force`` is True. Always checks ffmpeg whenever yt-dlp is updated.
    """
    if not _lock.acquire(blocking=False):
        return {"ok": True, "skipped": True, "reason": "already running"}

    try:
        stamp = _read_stamp()
        last_wall = stamp.get("last_check_unix")
        now_unix = time.time()
        if not force and isinstance(last_wall, (int, float)):
            if now_unix - float(last_wall) < MIN_NETWORK_GAP_SEC:
                return {
                    "ok": True,
                    "skipped": True,
                    "reason": "checked recently",
                    "seconds_remaining": round(
                        MIN_NETWORK_GAP_SEC - (now_unix - float(last_wall))
                    ),
                }

        ytdlp_result = _update_ytdlp()
        # Same pass: verify/refresh ffmpeg whenever we touch yt-dlp
        ffmpeg_result = _ensure_ffmpeg(refresh=True)

        ok = bool(ytdlp_result.get("ok")) and bool(ffmpeg_result.get("ok"))
        err_parts = []
        if ytdlp_result.get("error"):
            err_parts.append(f"yt-dlp: {ytdlp_result['error']}")
        if ffmpeg_result.get("error") and not ffmpeg_result.get("ok"):
            err_parts.append(f"ffmpeg: {ffmpeg_result['error']}")

        _write_stamp(
            last_check_unix=now_unix,
            last_ok=ok,
            last_error="; ".join(err_parts) if err_parts else None,
            last_action=ytdlp_result.get("action"),
            version=ytdlp_result.get("version"),
            ffmpeg_action=ffmpeg_result.get("action"),
            ffmpeg_version=ffmpeg_result.get("version"),
            ffmpeg_path=ffmpeg_result.get("path"),
        )
        return {
            "ok": ok,
            "ytdlp": ytdlp_result,
            "ffmpeg": ffmpeg_result,
        }
    finally:
        _lock.release()
