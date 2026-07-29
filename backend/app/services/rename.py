"""Rename/organize downloaded files to a Plex-friendly naming scheme.

Recommended layout (Personal Media / Local Assets — date-based shows):

  LibraryRoot/
    Channel Name/
      poster.jpg
      fanart.jpg
      YYYY-MM-DD - Episode Title [youtubeId].ext

Never invent 0000-00-00. If the upload date is unknown, omit the date prefix.
Channel name lives in the folder — do not repeat it in the filename.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import get_config
from ..models import MonitoredSource, Video, VideoStatus


_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_DATE_IN_NAME = re.compile(r"(?<!\d)(20\d{2}|19\d{2})[-_.](\d{2})[-_.](\d{2})(?!\d)")
_COMPACT_DATE = re.compile(r"(?<!\d)((?:20|19)\d{2})(\d{2})(\d{2})(?!\d)")


@dataclass
class RenamePlan:
    video_db_id: int
    youtube_id: str
    title: str
    source_title: str
    current_path: str | None
    new_path: str
    needs_rename: bool
    reason: str | None = None


def _safe_name(text: str, max_len: int = 180) -> str:
    cleaned = _ILLEGAL.sub("", text).strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return (cleaned[:max_len] or "Untitled").rstrip(" .")


def _date_from_filename(name: str) -> str | None:
    m = _DATE_IN_NAME.search(name)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = _COMPACT_DATE.search(name)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def _date_prefix(video: Video, current: Path | None = None) -> str | None:
    """Return YYYY-MM-DD or None — never fabricate 0000-00-00."""
    if video.published_at:
        return video.published_at.strftime("%Y-%m-%d")
    if current:
        parsed = _date_from_filename(current.name)
        if parsed:
            return parsed
        try:
            ts = current.stat().st_mtime
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        except OSError:
            pass
    return None


def desired_relative_path(
    source: MonitoredSource,
    video: Video,
    ext: str,
    *,
    current: Path | None = None,
) -> Path:
    folder = _safe_name(source.folder_name or source.title or "Unknown")
    title = _safe_name(video.title, 200)
    date = _date_prefix(video, current)
    if date:
        filename = f"{date} - {title} [{video.video_id}].{ext.lstrip('.')}"
    else:
        filename = f"{title} [{video.video_id}].{ext.lstrip('.')}"
    return Path(folder) / filename


def _library_root_for(source: MonitoredSource | None) -> Path:
    cfg = get_config()
    if source and (source.media_type or "video") == "audio":
        return Path(cfg.music_library_root)
    return Path(cfg.library_root)


def _find_file_by_id(library_root: Path, video_id: str) -> Path | None:
    if not library_root.exists():
        return None
    needle = f"[{video_id}]"
    for path in library_root.rglob("*"):
        if not path.is_file():
            continue
        if path.name in {"poster.jpg", "fanart.jpg"}:
            continue
        if needle in path.name:
            return path
    return None


def _resolve_current(library_root: Path, video: Video) -> Path | None:
    if video.file_path:
        p = Path(video.file_path)
        if p.exists():
            return p
    return _find_file_by_id(library_root, video.video_id)


def apply_path_mapping(path: str) -> str:
    """Translate a host library path to the Plex-visible path when mappings exist."""
    cfg = get_config()
    mappings = getattr(cfg, "path_mappings", None) or []
    if not mappings or not path:
        return path
    normalized = path.replace("/", "\\")
    for mapping in mappings:
        host = (mapping.host_path or "").strip().rstrip("\\/")
        plex = (mapping.plex_path or "").strip().rstrip("\\/")
        if not host or not plex:
            continue
        host_n = host.replace("/", "\\")
        if normalized.lower().startswith(host_n.lower()):
            rest = normalized[len(host_n) :]
            # Preserve plex path separators when plex looks POSIX
            if "/" in plex and "\\" not in plex:
                return plex.rstrip("/") + rest.replace("\\", "/")
            return plex.rstrip("\\/") + rest
    return path


def preview_renames(db: Session, source_id: int | None = None) -> list[RenamePlan]:
    q = (
        db.query(Video)
        .join(MonitoredSource)
        .filter(Video.status == VideoStatus.DOWNLOADED.value)
    )
    if source_id is not None:
        q = q.filter(Video.source_id == source_id)
    videos = q.order_by(MonitoredSource.title.asc(), Video.published_at.asc()).all()

    plans: list[RenamePlan] = []
    for video in videos:
        source = video.source
        library_root = _library_root_for(source)
        current = _resolve_current(library_root, video)
        if not current:
            # Also try the other root in case media_type was switched
            cfg = get_config()
            alt = Path(cfg.library_root)
            if alt != library_root:
                current = _resolve_current(alt, video)
            if not current:
                alt = Path(cfg.music_library_root)
                if alt != library_root:
                    current = _resolve_current(alt, video)
        if not current:
            plans.append(
                RenamePlan(
                    video_db_id=video.id,
                    youtube_id=video.video_id,
                    title=video.title,
                    source_title=source.title if source else "?",
                    current_path=video.file_path,
                    new_path="",
                    needs_rename=False,
                    reason="File not found on disk",
                )
            )
            continue

        rel = desired_relative_path(source, video, current.suffix, current=current)
        target = library_root / rel
        needs = current.resolve() != target.resolve()
        plans.append(
            RenamePlan(
                video_db_id=video.id,
                youtube_id=video.video_id,
                title=video.title,
                source_title=source.title if source else "?",
                current_path=str(current),
                new_path=str(target),
                needs_rename=needs,
                reason=None if needs else "Already correct",
            )
        )
    return plans


def apply_renames(
    db: Session,
    *,
    source_id: int | None = None,
    video_ids: list[int] | None = None,
) -> dict:
    plans = preview_renames(db, source_id=source_id)
    if video_ids is not None:
        wanted = set(video_ids)
        plans = [p for p in plans if p.video_db_id in wanted]

    renamed = 0
    skipped = 0
    errors: list[str] = []

    for plan in plans:
        if not plan.needs_rename:
            skipped += 1
            continue
        if not plan.current_path or not plan.new_path:
            skipped += 1
            continue
        src = Path(plan.current_path)
        dst = Path(plan.new_path)
        try:
            if not src.exists():
                errors.append(f"{plan.youtube_id}: source missing")
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists() and dst.resolve() != src.resolve():
                errors.append(f"{plan.youtube_id}: target already exists")
                continue
            shutil.move(str(src), str(dst))
            video = db.get(Video, plan.video_db_id)
            if video:
                video.file_path = str(dst)
                db.add(video)
            renamed += 1

            try:
                parent = src.parent
                if parent.exists() and not any(parent.iterdir()):
                    parent.rmdir()
            except OSError:
                pass
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{plan.youtube_id}: {exc}")

    db.commit()
    return {
        "renamed": renamed,
        "skipped": skipped,
        "errors": errors,
        "planned": len(plans),
    }
