"""Single source of truth for the ytarr app version (repo VERSION file)."""
from __future__ import annotations

from functools import lru_cache

from .paths import project_root, resource_path


@lru_cache(maxsize=1)
def app_version() -> str:
    for candidate in (project_root() / "VERSION", resource_path("VERSION")):
        try:
            text = candidate.read_text(encoding="utf-8").strip()
            if text:
                return text.splitlines()[0].strip()
        except OSError:
            continue
    return "0.0.0"
