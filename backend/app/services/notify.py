"""Connect notifications — webhook / Discord-style POST on library events."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from ..config import get_config

log = logging.getLogger("ytarr.notify")


def _post_json(url: str, payload: dict[str, Any]) -> None:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "ytarr"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
        _ = resp.read()


def _webhook_url() -> str:
    return (getattr(get_config(), "connect_webhook_url", "") or "").strip()


def on_library_import(*, host_file_path: str | Path | None = None, media_type: str = "video") -> None:
    if not getattr(get_config(), "connect_on_download", True):
        return
    url = _webhook_url()
    if not url:
        return
    name = Path(host_file_path).name if host_file_path else "library"
    payload = {
        "content": f"ytarr imported ({media_type}): {name}",
        "embeds": [
            {
                "title": "ytarr import",
                "description": str(host_file_path or ""),
                "fields": [{"name": "media_type", "value": media_type}],
            }
        ],
    }
    try:
        _post_json(url, payload)
    except Exception as exc:  # noqa: BLE001
        log.warning("Webhook failed: %s", exc)


def on_download_failure(*, title: str, error: str) -> None:
    if not getattr(get_config(), "connect_on_failure", True):
        return
    url = _webhook_url()
    if not url:
        return
    payload = {
        "content": f"ytarr download failed: {title}",
        "embeds": [{"title": title or "Download failed", "description": (error or "")[:1500]}],
    }
    try:
        _post_json(url, payload)
    except Exception as exc:  # noqa: BLE001
        log.warning("Webhook failed: %s", exc)


def on_grab(*, title: str, video_id: str, source_title: str | None = None) -> None:
    """Notify when Interactive Search / manual grab queues a download."""
    if not getattr(get_config(), "connect_on_grab", False):
        return
    url = _webhook_url()
    if not url:
        return
    label = source_title or "series"
    payload = {
        "content": f"ytarr grab: {title}",
        "embeds": [
            {
                "title": title or "Grabbed",
                "description": f"Queued under {label}",
                "fields": [{"name": "youtube_id", "value": video_id or "—"}],
            }
        ],
    }
    try:
        _post_json(url, payload)
    except Exception as exc:  # noqa: BLE001
        log.warning("Webhook failed: %s", exc)
