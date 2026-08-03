"""Resolve project paths for source runs and frozen (PyInstaller) builds."""
from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False)) and hasattr(sys, "_MEIPASS")


def bundle_dir() -> Path:
    """Where PyInstaller unpacks bundled read-only resources (MEIPASS)."""
    if is_frozen():
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    # backend/app/paths.py -> parents[2] = project root in source tree
    return Path(__file__).resolve().parents[2]


def project_root() -> Path:
    """Writable install root: folder containing ytarr.exe, or repo root in dev."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def resource_path(*parts: str) -> Path:
    """Prefer a file next to the exe; fall back to the frozen bundle."""
    local = project_root().joinpath(*parts)
    if local.exists():
        return local
    bundled = bundle_dir().joinpath(*parts)
    if bundled.exists():
        return bundled
    return local
