"""Rename/organize downloaded files to Plex-friendly layouts.

Video (TV-style Personal Media):
  LibraryRoot/
    Channel Name/
      poster.jpg
      YYYY-MM-DD - Episode Title [youtubeId].ext

Music (Plex Music artist folders + embedded MusicBrainz tags):
  MusicRoot/
    Artist Name/
      Track Title.ext

Never invent 0000-00-00. If the upload date is unknown for video, omit the date prefix.
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


def _is_audio(source: MonitoredSource | None) -> bool:
    return bool(source) and (source.media_type or "video").strip().lower() == "audio"


def _music_artist_folder(
    source: MonitoredSource,
    video: Video,
    current: Path | None = None,
) -> str:
    """Plex Music artist folder — never use the track title as the artist."""
    track = _safe_name(video.title or "", 200)
    candidates: list[str] = []

    folder = (source.folder_name or "").strip()
    if folder:
        candidates.append(folder)
    if source.source_type == "channel" and (source.title or "").strip():
        candidates.append(source.title.strip())
    if current and current.parent.is_dir():
        parent = current.parent.name.strip()
        root_names = {
            Path(get_config().music_library_root).name.lower(),
            Path(get_config().library_root).name.lower(),
            "music",
            "library",
        }
        if parent and parent.lower() not in root_names:
            candidates.append(parent)

    for raw in candidates:
        safe = _safe_name(raw)
        if not safe:
            continue
        # Reject when folder was wrongly set to the song title (single-track adds)
        if track and safe.lower() == track.lower():
            continue
        return safe
    return "Unknown Artist"


def music_artist_folder(
    source: MonitoredSource,
    video: Video,
    current: Path | None = None,
) -> str:
    """Public helper: Plex Music artist folder name for a track."""
    return _music_artist_folder(source, video, current)


def desired_relative_path(
    source: MonitoredSource,
    video: Video,
    ext: str,
    *,
    current: Path | None = None,
) -> Path:
    ext = ext.lstrip(".") or "mp4"
    title = _safe_name(video.title, 200)

    if _is_audio(source):
        # Plex Music: Artist / Title.ext — no YouTube [id] (Plex uses embedded tags / MB)
        artist = _music_artist_folder(source, video, current)
        filename = f"{title}.{ext}"
        target = Path(artist) / filename
        # Disambiguate collisions without agent-style [brackets]
        if current is not None:
            try:
                library_root = _library_root_for(source)
                full = library_root / target
                if full.exists() and full.resolve() != current.resolve():
                    filename = f"{title} ({video.video_id}).{ext}"
                    target = Path(artist) / filename
            except OSError:
                pass
        return target

    folder = _safe_name(source.folder_name or source.title or "Unknown")
    date = _date_prefix(video, current)
    if date:
        filename = f"{date} - {title} [{video.video_id}].{ext}"
    else:
        filename = f"{title} [{video.video_id}].{ext}"
    return Path(folder) / filename


def _library_root_for(source: MonitoredSource | None) -> Path:
    cfg = get_config()
    if _is_audio(source):
        return Path(cfg.music_library_root)
    return Path(cfg.library_root)


def _find_file_by_id(library_root: Path, video_id: str) -> Path | None:
    if not library_root.exists():
        return None
    needles = (f"[{video_id}]", f"({video_id})")
    for path in library_root.rglob("*"):
        if not path.is_file():
            continue
        if path.name in {"poster.jpg", "fanart.jpg"}:
            continue
        if any(n in path.name for n in needles):
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
            if "/" in plex and "\\" not in plex:
                return plex.rstrip("/") + rest.replace("\\", "/")
            return plex.rstrip("\\/") + rest
    return path


def organize_downloaded_file(
    db: Session,
    video: Video,
    source: MonitoredSource | None,
    current: Path,
) -> Path:
    """Move a freshly downloaded file into the Plex layout. Updates video.file_path."""
    if not source or not current.exists():
        return current
    library_root = _library_root_for(source)
    rel = desired_relative_path(source, video, current.suffix, current=current)
    target = library_root / rel
    try:
        if current.resolve() == target.resolve():
            video.file_path = str(current)
            # Heal music folder_name if it was the track title
            if _is_audio(source):
                artist = _music_artist_folder(source, video, current)
                if (source.folder_name or "").strip().lower() != artist.lower():
                    source.folder_name = artist
                    db.add(source)
            db.add(video)
            return current

        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.resolve() != current.resolve():
            # Keep existing correct file; drop the new duplicate download path
            video.file_path = str(target)
            db.add(video)
            try:
                current.unlink(missing_ok=True)
            except OSError:
                pass
            return target

        shutil.move(str(current), str(target))
        video.file_path = str(target)
        db.add(video)

        if _is_audio(source):
            artist = target.parent.name
            if artist and (source.folder_name or "").strip().lower() != artist.lower():
                source.folder_name = artist
                db.add(source)

        try:
            parent = current.parent
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
        except OSError:
            pass
        return target
    except OSError:
        video.file_path = str(current)
        db.add(video)
        return current


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
            video = db.get(Video, plan.video_db_id)
            source = video.source if video else None
            if video and source:
                organize_downloaded_file(db, video, source, src)
                if video.file_path and Path(video.file_path).exists():
                    renamed += 1
                else:
                    errors.append(f"{plan.youtube_id}: organize failed")
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists() and dst.resolve() != src.resolve():
                    errors.append(f"{plan.youtube_id}: target already exists")
                    continue
                shutil.move(str(src), str(dst))
                if video:
                    video.file_path = str(dst)
                    db.add(video)
                renamed += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{plan.youtube_id}: {exc}")

    db.commit()
    return {
        "renamed": renamed,
        "skipped": skipped,
        "errors": errors,
        "planned": len(plans),
    }
