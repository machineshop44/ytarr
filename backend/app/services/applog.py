"""Rotating application log for System → Log (Sonarr-style)."""
from __future__ import annotations

import logging
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from ..config import get_config
from ..paths import project_root

_configured = False
_lock = threading.Lock()
_LOGGER_NAME = "ytarr"


def log_file_path() -> Path:
    try:
        data = Path(get_config().data_dir)
    except Exception:
        data = project_root() / "data"
    data.mkdir(parents=True, exist_ok=True)
    return data / "ytarr-app.log"


def setup_app_logging() -> Path:
    """Attach a rotating file handler to the ytarr logger tree (idempotent)."""
    global _configured
    path = log_file_path()
    with _lock:
        if _configured:
            return path
        root = logging.getLogger(_LOGGER_NAME)
        root.setLevel(logging.INFO)
        # Avoid duplicate handlers on reload
        for h in list(root.handlers):
            if getattr(h, "_ytarr_app_log", False):
                root.removeHandler(h)
        handler = RotatingFileHandler(
            path,
            maxBytes=2_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s|%(levelname)s|%(name)s|%(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        handler._ytarr_app_log = True  # type: ignore[attr-defined]
        root.addHandler(handler)
        # Also capture update / musicbrainz under ytarr.*
        logging.getLogger("ytarr.ytdlp_update").setLevel(logging.INFO)
        _configured = True
        root.info("Application log started → %s", path)
    return path


def get_logger(name: str = _LOGGER_NAME) -> logging.Logger:
    if not name.startswith(_LOGGER_NAME):
        name = f"{_LOGGER_NAME}.{name}"
    return logging.getLogger(name)


def log_info(message: str, *, source: str = "app") -> None:
    get_logger(source).info("%s", message)


def log_warning(message: str, *, source: str = "app") -> None:
    get_logger(source).warning("%s", message)


def log_error(message: str, *, source: str = "app") -> None:
    get_logger(source).error("%s", message)


def read_log_text(*, max_bytes: int = 256_000) -> str:
    """Return the tail of the app log (and tray log if present) as plain text."""
    setup_app_logging()
    chunks: list[str] = []
    app_path = log_file_path()
    if app_path.exists():
        chunks.append(_read_tail(app_path, max_bytes=max_bytes))

    tray = project_root() / "data" / "ytarr-tray.log"
    try:
        cfg_tray = Path(get_config().data_dir) / "ytarr-tray.log"
        if cfg_tray.exists():
            tray = cfg_tray
    except Exception:
        pass
    if tray.exists() and tray.resolve() != app_path.resolve():
        tray_text = _read_tail(tray, max_bytes=max_bytes // 2)
        if tray_text.strip():
            chunks.append("--- ytarr-tray.log ---\n" + tray_text)

    return "\n".join(chunks) if chunks else "(log empty — no events yet)\n"


def clear_logs() -> dict:
    """Truncate app (+ tray) logs so System → Log starts fresh."""
    setup_app_logging()
    cleared: list[str] = []
    with _lock:
        app_path = log_file_path()
        try:
            # Flush rotating handlers then truncate
            root = logging.getLogger(_LOGGER_NAME)
            for h in root.handlers:
                try:
                    h.flush()
                except Exception:
                    pass
            app_path.write_text("", encoding="utf-8")
            cleared.append(str(app_path))
        except OSError as exc:
            return {"ok": False, "error": str(exc), "cleared": cleared}

        tray_candidates = [project_root() / "data" / "ytarr-tray.log"]
        try:
            tray_candidates.insert(0, Path(get_config().data_dir) / "ytarr-tray.log")
        except Exception:
            pass
        seen: set[str] = set()
        for tray in tray_candidates:
            try:
                key = str(tray.resolve())
            except OSError:
                key = str(tray)
            if key in seen or not tray.exists():
                continue
            seen.add(key)
            try:
                tray.write_text("", encoding="utf-8")
                cleared.append(str(tray))
            except OSError:
                pass

    log_info("Log cleared by user", source="system")
    return {"ok": True, "cleared": cleared}


def _read_tail(path: Path, *, max_bytes: int) -> str:
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
                f.readline()  # drop partial first line
            data = f.read()
        return data.decode("utf-8", errors="replace")
    except OSError as exc:
        return f"(could not read {path}: {exc})\n"
