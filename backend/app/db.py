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
    _ensure_sqlite_columns()
    _migrate_video_unique_constraint()
    _ensure_indexes()


def _ensure_indexes() -> None:
    """Hot-path indexes for queue/dashboard/library filters."""
    stmts = (
        "CREATE INDEX IF NOT EXISTS ix_videos_status ON videos (status)",
        "CREATE INDEX IF NOT EXISTS ix_videos_source_status ON videos (source_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_download_jobs_status ON download_jobs (status)",
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
        },
    }
    with engine.begin() as conn:
        for table, cols in wanted.items():
            existing = {
                row[1]
                for row in conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
            }
            for name, ddl in cols.items():
                if name not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def _migrate_video_unique_constraint() -> None:
    """Replace global video_id unique with (source_id, video_id) so playlists can list dupes."""
    with engine.begin() as conn:
        indexes = conn.exec_driver_sql("PRAGMA index_list(videos)").fetchall()
        # row: (seq, name, unique, origin, partial)
        index_names = {row[1] for row in indexes}
        if "uq_videos_source_video" in index_names and "uq_videos_video_id" not in index_names:
            return

        needs = "uq_videos_video_id" in index_names or "uq_videos_source_video" not in index_names
        if not needs:
            return

        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        conn.exec_driver_sql("DROP TABLE IF EXISTS videos_new")
        conn.exec_driver_sql(
            """
            CREATE TABLE videos_new (
                id INTEGER NOT NULL PRIMARY KEY,
                source_id INTEGER NOT NULL,
                video_id VARCHAR(64) NOT NULL,
                title VARCHAR(512) NOT NULL,
                published_at DATETIME,
                duration INTEGER,
                thumbnail_url VARCHAR(1024),
                file_path VARCHAR(2048),
                status VARCHAR(32) NOT NULL,
                error TEXT,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                FOREIGN KEY(source_id) REFERENCES monitored_sources (id) ON DELETE CASCADE,
                CONSTRAINT uq_videos_source_video UNIQUE (source_id, video_id)
            )
            """
        )
        conn.exec_driver_sql(
            """
            INSERT INTO videos_new
                (id, source_id, video_id, title, published_at, duration, thumbnail_url,
                 file_path, status, error, created_at, updated_at)
            SELECT id, source_id, video_id, title, published_at, duration, thumbnail_url,
                   file_path, status, error, created_at, updated_at
            FROM videos
            ORDER BY id ASC
            """
        )
        conn.exec_driver_sql("DROP TABLE videos")
        conn.exec_driver_sql("ALTER TABLE videos_new RENAME TO videos")
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_videos_video_id ON videos (video_id)"
        )
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")

