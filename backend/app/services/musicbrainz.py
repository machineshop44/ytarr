"""MusicBrainz lookup + embed tags for Plex Music.

Plex Music does not match via bracket IDs in filenames. It uses folder layout
(Artist/…) and embedded tags — including MusicBrainz recording/release IDs
when present (prefer local metadata / MusicBrainz tags).

YouTube ids in [brackets] are not TVDB/MBIDs; for music we keep them out of
the filename and put the YouTube id in a comment tag for ytarr only.
"""
from __future__ import annotations

import logging
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from . import ytdlp

log = logging.getLogger(__name__)

_UA = "ytarr/0.1 (https://github.com/local/ytarr; music metadata)"
_last_request = 0.0
_CACHE: dict[str, "MusicBrainzMatch | None"] = {}


@dataclass
class MusicBrainzMatch:
    recording_id: str
    recording_title: str
    artist_name: str
    artist_id: str | None = None
    release_id: str | None = None
    release_title: str | None = None
    score: int = 0


def _throttle() -> None:
    global _last_request
    elapsed = time.monotonic() - _last_request
    if elapsed < 1.05:
        time.sleep(1.05 - elapsed)
    _last_request = time.monotonic()


def _clean_query_title(title: str) -> str:
    """Strip common YouTube noise so MB search works better."""
    t = title.strip()
    # Drop trailing parentheticals that are often live/video tags
    t = re.sub(
        r"\s*[\(\[][^)\]]*(official|video|audio|lyrics|visuali[sz]er|hd|4k|mv)[^)\]]*[\)\]]\s*",
        " ",
        t,
        flags=re.I,
    )
    t = re.sub(r"\s{2,}", " ", t).strip(" -")
    return t or title.strip()


def lookup_recording(artist: str, title: str) -> MusicBrainzMatch | None:
    artist = (artist or "").strip()
    title = _clean_query_title(title or "")
    if not artist or not title or artist.lower() in {"unknown artist", "unknown"}:
        return None

    cache_key = f"{artist.lower()}::{title.lower()}"
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    # Prefer exact-ish recording + artist; fall back to looser query
    queries = [
        f'recording:"{title}" AND artist:"{artist}"',
        f"{title} AND artist:{artist}",
    ]
    match: MusicBrainzMatch | None = None
    try:
        with httpx.Client(
            base_url="https://musicbrainz.org/ws/2/",
            headers={"User-Agent": _UA, "Accept": "application/json"},
            timeout=20.0,
        ) as client:
            for q in queries:
                _throttle()
                resp = client.get(
                    "recording",
                    params={"query": q, "fmt": "json", "limit": 5},
                )
                if resp.status_code == 503:
                    time.sleep(1.5)
                    continue
                resp.raise_for_status()
                recordings = resp.json().get("recordings") or []
                if not recordings:
                    continue
                best = max(recordings, key=lambda r: int(r.get("score") or 0))
                score = int(best.get("score") or 0)
                if score < 60:
                    continue
                credit = (best.get("artist-credit") or [{}])[0]
                artist_obj = credit.get("artist") or {}
                releases = best.get("releases") or []
                release = releases[0] if releases else {}
                match = MusicBrainzMatch(
                    recording_id=str(best.get("id") or ""),
                    recording_title=str(best.get("title") or title),
                    artist_name=str(
                        credit.get("name") or artist_obj.get("name") or artist
                    ),
                    artist_id=str(artist_obj["id"]) if artist_obj.get("id") else None,
                    release_id=str(release["id"]) if release.get("id") else None,
                    release_title=str(release["title"]) if release.get("title") else None,
                    score=score,
                )
                if match.recording_id:
                    break
                match = None
    except Exception as exc:  # noqa: BLE001
        log.warning("MusicBrainz lookup failed for %s — %s: %s", artist, title, exc)
        match = None

    _CACHE[cache_key] = match
    return match


def embed_audio_tags(
    path: Path,
    *,
    title: str,
    artist: str,
    album: str | None = None,
    album_artist: str | None = None,
    youtube_id: str | None = None,
    mb: MusicBrainzMatch | None = None,
) -> bool:
    """Write ID3/iTunes-style tags with ffmpeg (required for m4a music downloads)."""
    ffmpeg = ytdlp.resolve_ffmpeg()
    if not ffmpeg or not path.exists():
        return False

    album = (album or (mb.release_title if mb else None) or "YouTube").strip()
    album_artist = (album_artist or artist).strip()
    track_title = (mb.recording_title if mb else title).strip() or title
    track_artist = (mb.artist_name if mb else artist).strip() or artist

    tmp = path.with_name(path.stem + ".__ytarr_tag__" + path.suffix)
    args = [
        str(ffmpeg),
        "-y",
        "-i",
        str(path),
        "-map",
        "0",
        "-c",
        "copy",
        "-map_metadata",
        "-1",
        "-metadata",
        f"title={track_title}",
        "-metadata",
        f"artist={track_artist}",
        "-metadata",
        f"album_artist={album_artist}",
        "-metadata",
        f"album={album}",
    ]
    if youtube_id:
        args.extend(["-metadata", f"comment=youtube-id={youtube_id}"])
    if mb:
        # Common ffmpeg / mutagen-compatible MusicBrainz keys for Plex
        args.extend(["-metadata", f"musicbrainz_trackid={mb.recording_id}"])
        if mb.artist_id:
            args.extend(["-metadata", f"musicbrainz_artistid={mb.artist_id}"])
        if mb.release_id:
            args.extend(["-metadata", f"musicbrainz_albumid={mb.release_id}"])

    args.append(str(tmp))
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
        if result.returncode != 0 or not tmp.exists():
            log.warning(
                "ffmpeg tag write failed for %s: %s",
                path.name,
                (result.stderr or result.stdout or "")[-400:],
            )
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            return False
        tmp.replace(path)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("ffmpeg tag write error for %s: %s", path, exc)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def enrich_music_file(
    path: Path,
    *,
    title: str,
    artist: str,
    youtube_id: str | None = None,
) -> MusicBrainzMatch | None:
    """Lookup MusicBrainz and embed tags. Returns the match if found."""
    mb = lookup_recording(artist, title)
    embed_audio_tags(
        path,
        title=title,
        artist=artist,
        youtube_id=youtube_id,
        mb=mb,
    )
    return mb
