"""Rename/organize downloaded files to ytarr's Plex-friendly naming scheme."""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import get_config
from ..models import MonitoredSource, Video, VideoStatus


_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_ID_IN_NAME = re.compile(r"\[([A-Za-z0-9_-]{6,})\]")


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


def _date_prefix(video: Video) -> str:
    if video.published_at:
        return video.published_at.strftime("%Y-%m-%d")
    return "0000-00-00"


def desired_relative_path(source: MonitoredSource, video: Video, ext: str) -> Path:
    folder = _safe_name(source.folder_name or source.title or "Unknown")
    filename = f"{_date_prefix(video)} - {_safe_name(video.title, 200)} [{video.video_id}].{ext.lstrip('.')}"
    return Path(folder) / filename


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


def preview_renames(db: Session, source_id: int | None = None) -> list[RenamePlan]:
    cfg = get_config()
    library_root = Path(cfg.library_root)
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
        current = _resolve_current(library_root, video)
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

        rel = desired_relative_path(source, video, current.suffix)
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

            # Clean empty leftover folders (but never delete folder with poster/fanart)
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
