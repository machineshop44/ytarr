"""Manual import — scan library folders for [youtubeId] files and link to catalog."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ..config import get_config
from ..models import MonitoredSource, Video, VideoStatus

_ID_RE = re.compile(r"\[([A-Za-z0-9_-]{6,20})\]|\(([A-Za-z0-9_-]{6,20})\)")


def _extract_id(name: str) -> str | None:
    m = _ID_RE.search(name)
    if not m:
        return None
    return m.group(1) or m.group(2)


def scan_orphans(db: Session, *, limit: int = 200) -> list[dict[str, Any]]:
    cfg = get_config()
    roots = [Path(cfg.library_root), Path(cfg.music_library_root)]
    known_paths = {
        str(Path(v.file_path)).lower()
        for v in db.query(Video.file_path).filter(Video.file_path.isnot(None)).all()
        if v.file_path
    }
    known_ids = {v.video_id for v in db.query(Video.video_id).all()}
    orphans: list[dict[str, Any]] = []
    for root in roots:
        if not root.exists():
            continue
        try:
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                if path.suffix.lower() not in {
                    ".mkv",
                    ".mp4",
                    ".webm",
                    ".m4a",
                    ".mp3",
                    ".opus",
                    ".flac",
                    ".avi",
                }:
                    continue
                if str(path).lower() in known_paths:
                    continue
                vid = _extract_id(path.name)
                if not vid:
                    continue
                orphans.append(
                    {
                        "path": str(path),
                        "video_id": vid,
                        "title": path.stem,
                        "already_in_db": vid in known_ids,
                    }
                )
                if len(orphans) >= limit:
                    return orphans
        except OSError:
            continue
    return orphans


def import_files(
    db: Session,
    items: list[dict[str, Any]],
    *,
    source_id: int | None = None,
) -> dict[str, Any]:
    """Attach files to existing videos or create under a source."""
    imported = 0
    skipped = 0
    errors: list[str] = []
    source: MonitoredSource | None = None
    if source_id is not None:
        source = db.get(MonitoredSource, source_id)
        if not source:
            raise ValueError("source_id not found")

    for item in items:
        path = Path(str(item.get("path") or ""))
        vid = str(item.get("video_id") or _extract_id(path.name) or "").strip()
        if not path.exists() or not vid:
            skipped += 1
            continue
        existing = (
            db.query(Video)
            .filter(Video.video_id == vid)
            .order_by(Video.id.asc())
            .first()
        )
        if existing:
            existing.file_path = str(path)
            existing.status = VideoStatus.DOWNLOADED.value
            existing.error = None
            db.add(existing)
            imported += 1
            continue
        if not source:
            errors.append(f"{vid}: no matching video and no source_id")
            skipped += 1
            continue
        row = Video(
            source_id=source.id,
            video_id=vid,
            title=str(item.get("title") or path.stem),
            file_path=str(path),
            status=VideoStatus.DOWNLOADED.value,
        )
        db.add(row)
        imported += 1
    db.commit()
    return {"imported": imported, "skipped": skipped, "errors": errors}
