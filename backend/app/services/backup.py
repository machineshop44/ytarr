"""System backup / restore for config.yaml + SQLite DB (Arr-style)."""

from __future__ import annotations

import shutil
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import config_file_path, get_config


def backup_dir() -> Path:
    root = Path(get_config().data_dir) / "backups"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _resolve_db_path(data_dir: Path) -> Path:
    db_path = data_dir / "ytarr.db"
    if db_path.exists():
        return db_path
    for cand in data_dir.glob("*.db"):
        return cand
    return db_path


def _snapshot_sqlite(db_path: Path, dest: Path) -> None:
    """Consistent snapshot that includes WAL pages (unlike a raw file copy)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    src = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=60)
    try:
        dst = sqlite3.connect(str(dest), timeout=60)
        try:
            src.backup(dst)
            dst.commit()
        finally:
            dst.close()
    finally:
        src.close()


def create_backup() -> dict[str, Any]:
    cfg = get_config()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = backup_dir() / f"ytarr-backup-{stamp}.zip"
    config_path = config_file_path()
    data_dir = Path(cfg.data_dir)
    db_path = _resolve_db_path(data_dir)
    snap: Path | None = None

    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if config_path.exists():
            zf.write(config_path, arcname="config.yaml")
        if db_path.exists():
            snap = data_dir / f".ytarr-backup-snap-{stamp}.db"
            _snapshot_sqlite(db_path, snap)
            zf.write(snap, arcname=db_path.name)
        meta = f"created={stamp}\nconfig={config_path}\ndb={db_path}\nsnapshot=sqlite3.backup\n"
        zf.writestr("backup.txt", meta)

    if snap is not None:
        try:
            snap.unlink(missing_ok=True)
        except OSError:
            pass

    return {
        "ok": True,
        "path": str(dest),
        "name": dest.name,
        "size": dest.stat().st_size,
    }


def list_backups() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for p in sorted(backup_dir().glob("ytarr-backup-*.zip"), reverse=True):
        items.append(
            {
                "name": p.name,
                "path": str(p),
                "size": p.stat().st_size,
                "mtime": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(),
            }
        )
    return items


def restore_backup(name: str) -> dict[str, Any]:
    """Restore config/DB from a zip. Caller must restart the app before using the DB again."""
    safe = Path(name).name
    src = backup_dir() / safe
    if not src.exists():
        raise FileNotFoundError(f"Backup not found: {safe}")
    cfg = get_config()
    config_path = config_file_path()
    data_dir = Path(cfg.data_dir)
    restored: list[str] = []
    with zipfile.ZipFile(src, "r") as zf:
        names = zf.namelist()
        if "config.yaml" in names:
            tmp = data_dir / "config.restore.yaml"
            with zf.open("config.yaml") as src_f, tmp.open("wb") as out:
                shutil.copyfileobj(src_f, out)
            shutil.move(str(tmp), str(config_path))
            restored.append("config.yaml")
        for n in names:
            if n.endswith(".db"):
                target = data_dir / Path(n).name
                tmp = data_dir / f"{Path(n).name}.restore"
                with zf.open(n) as src_f, tmp.open("wb") as out:
                    shutil.copyfileobj(src_f, out)
                # Drop stale WAL so the restored main DB is authoritative
                for suffix in ("-wal", "-shm"):
                    side = Path(str(target) + suffix)
                    try:
                        side.unlink(missing_ok=True)
                    except OSError:
                        pass
                shutil.move(str(tmp), str(target))
                restored.append(Path(n).name)
    return {"ok": True, "restored": restored, "restart_required": True}
