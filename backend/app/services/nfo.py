"""Plex Local Media Assets / Home Videos NFO sidecars (synopsis/plot)."""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime
from pathlib import Path

from ..models import MonitoredSource, Video

log = logging.getLogger("ytarr.nfo")

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _xml_text(value: str | None, *, max_len: int = 8000) -> str:
    text = _CTRL.sub("", (value or "").strip())
    if len(text) > max_len:
        text = text[: max_len - 1].rstrip() + "…"
    return html.escape(text, quote=False)


def nfo_path_for(media_file: Path) -> Path:
    return media_file.with_suffix(".nfo")


def write_video_nfo(
    media_file: Path,
    video: Video,
    source: MonitoredSource | None = None,
    *,
    description: str | None = None,
) -> Path | None:
    """Write a movie-style NFO next to the video so Home Videos shows a synopsis."""
    if not media_file or not media_file.exists():
        return None
    if media_file.suffix.lower() in {".nfo", ".jpg", ".jpeg", ".png", ".txt"}:
        return None

    plot = (description or getattr(video, "description", None) or "").strip()
    title = (video.title or media_file.stem or "Untitled").strip()
    show = ""
    if source:
        show = (source.title or source.folder_name or "").strip()
    premiered = ""
    if video.published_at:
        premiered = video.published_at.strftime("%Y-%m-%d")

    season = int(getattr(source, "season_number", None) or 1) if source else 1
    episode = int(getattr(video, "episode_number", None) or 0) or None

    lines = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        "<movie>",
        f"  <title>{_xml_text(title, max_len=500)}</title>",
    ]
    if show:
        lines.append(f"  <studio>{_xml_text(show, max_len=200)}</studio>")
    if plot:
        lines.append(f"  <plot>{_xml_text(plot)}</plot>")
        lines.append(f"  <outline>{_xml_text(plot, max_len=2000)}</outline>")
    if premiered:
        lines.append(f"  <premiered>{premiered}</premiered>")
        try:
            year = datetime.strptime(premiered, "%Y-%m-%d").year
            lines.append(f"  <year>{year}</year>")
        except ValueError:
            pass
    if episode is not None:
        lines.append(f"  <season>{season}</season>")
        lines.append(f"  <episode>{episode}</episode>")
    lines.append(
        f'  <uniqueid type="youtube" default="true">{_xml_text(video.video_id, max_len=64)}</uniqueid>'
    )
    lines.append("</movie>")
    lines.append("")

    dest = nfo_path_for(media_file)
    try:
        dest.write_text("\n".join(lines), encoding="utf-8")
        return dest
    except OSError as exc:
        log.warning("Failed to write NFO %s: %s", dest, exc)
        return None
