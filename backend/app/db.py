from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import database_url


class Base(DeclarativeBase):
    pass


engine = create_engine(
    database_url(),
    connect_args={"check_same_thread": False, "timeout": 30},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:  # noqa: ARG001
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    # Unique-constraint rebuild must run before column ensure — the rebuild used to
    # drop newer columns (description / episode_number) when it ran after ALTER ADD.
    _migrate_video_unique_constraint()
    _ensure_sqlite_columns()
    _ensure_indexes()


def _ensure_indexes() -> None:
    """Hot-path indexes for queue/dashboard/library filters."""
    stmts = (
        "CREATE INDEX IF NOT EXISTS ix_videos_status ON videos (status)",
        "CREATE INDEX IF NOT EXISTS ix_videos_source_status ON videos (source_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_videos_source_published ON videos (source_id, published_at)",
        "CREATE INDEX IF NOT EXISTS ix_videos_published_at ON videos (published_at)",
        "CREATE INDEX IF NOT EXISTS ix_videos_updated_at ON videos (updated_at)",
        "CREATE INDEX IF NOT EXISTS ix_download_jobs_status ON download_jobs (status)",
        "CREATE INDEX IF NOT EXISTS ix_download_jobs_video_status ON download_jobs (video_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_monitored_sources_enabled ON monitored_sources (enabled)",
        "CREATE INDEX IF NOT EXISTS ix_monitored_sources_parent ON monitored_sources (parent_source_id)",
    )
    with engine.begin() as conn:
        for sql in stmts:
            conn.exec_driver_sql(sql)


def _ensure_sqlite_columns() -> None:
    """Add columns introduced after first create_all (SQLite has no ALTER IF NOT EXISTS)."""
    wanted = {
        "monitored_sources": {
            "quality": "VARCHAR(32) NOT NULL DEFAULT ''",
            "media_type": "VARCHAR(16) NOT NULL DEFAULT 'video'",
            "parent_source_id": "INTEGER REFERENCES monitored_sources(id) ON DELETE SET NULL",
            "tags": "VARCHAR(512) NOT NULL DEFAULT ''",
            "season_number": "INTEGER NOT NULL DEFAULT 1",
            "description": "TEXT",
            "subscriber_count": "INTEGER",
        },
        "videos": {
            "retry_count": "INTEGER NOT NULL DEFAULT 0",
            "description": "TEXT",
            "episode_number": "INTEGER",
        },
    }
    with engine.begin() as conn:
        for table, cols in wanted.items():
            existing = {
                row[1]
                for row in conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
            }
            if not existing:
                continue
            for name, ddl in cols.items():
                if name not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def _migrate_video_unique_constraint() -> None:
    """Replace global video_id unique with (source_id, video_id) so playlists can list dupes.

    Must disable foreign_keys outside a transaction — SQLite ignores PRAGMA foreign_keys
    changes that happen mid-transaction, and DROP TABLE videos would otherwise fail while
    download_jobs still references it.
    """
    raw = engine.raw_connection()
    try:
        raw.isolation_level = None  # autocommit — required for PRAGMA foreign_keys
        cur = raw.cursor()
        try:
            indexes = cur.execute("PRAGMA index_list(videos)").fetchall()
            index_names = {row[1] for row in indexes}
            if "uq_videos_source_video" in index_names and "uq_videos_video_id" not in index_names:
                return

            needs = "uq_videos_video_id" in index_names or "uq_videos_source_video" not in index_names
            if not needs:
                return

            cur.execute("PRAGMA foreign_keys=OFF")
            cur.execute("BEGIN")
            try:
                cur.execute("DROP TABLE IF EXISTS videos_new")
                cur.execute(
                    """
                    CREATE TABLE videos_new (
                        id INTEGER NOT NULL PRIMARY KEY,
                        source_id INTEGER NOT NULL,
                        video_id VARCHAR(64) NOT NULL,
                        title VARCHAR(512) NOT NULL,
                        published_at DATETIME,
                        duration INTEGER,
                        thumbnail_url VARCHAR(1024),
                        description TEXT,
                        episode_number INTEGER,
                        file_path VARCHAR(2048),
                        status VARCHAR(32) NOT NULL,
                        error TEXT,
                        retry_count INTEGER NOT NULL DEFAULT 0,
                        created_at DATETIME NOT NULL,
                        updated_at DATETIME NOT NULL,
                        FOREIGN KEY(source_id) REFERENCES monitored_sources (id) ON DELETE CASCADE,
                        CONSTRAINT uq_videos_source_video UNIQUE (source_id, video_id)
                    )
                    """
                )
                old_cols = {row[1] for row in cur.execute("PRAGMA table_info(videos)").fetchall()}
                fallbacks = {
                    "id": "NULL",
                    "source_id": "NULL",
                    "video_id": "NULL",
                    "title": "'Untitled'",
                    "published_at": "NULL",
                    "duration": "NULL",
                    "thumbnail_url": "NULL",
                    "description": "NULL",
                    "episode_number": "NULL",
                    "file_path": "NULL",
                    "status": "'wanted'",
                    "error": "NULL",
                    "retry_count": "0",
                    "created_at": "CURRENT_TIMESTAMP",
                    "updated_at": "CURRENT_TIMESTAMP",
                }
                targets = list(fallbacks)
                selects = [name if name in old_cols else fallbacks[name] for name in targets]
                cur.execute(
                    f"""
                    INSERT INTO videos_new ({", ".join(targets)})
                    SELECT {", ".join(selects)}
                    FROM videos
                    ORDER BY id ASC
                    """
                )
                cur.execute("DROP TABLE videos")
                cur.execute("ALTER TABLE videos_new RENAME TO videos")
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS ix_videos_video_id ON videos (video_id)"
                )
                cur.execute("COMMIT")
            except Exception:
                cur.execute("ROLLBACK")
                raise
            finally:
                cur.execute("PRAGMA foreign_keys=ON")
        finally:
            cur.close()
    finally:
        raw.close()

