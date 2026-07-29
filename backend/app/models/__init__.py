from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


class VideoStatus(str, Enum):
    WANTED = "wanted"
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    FAILED = "failed"
    IGNORED = "ignored"
    SEEN = "seen"


class MonitoredSource(Base):
    __tablename__ = "monitored_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    url: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="Unknown")
    yt_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="channel")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    monitor_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="new")
    folder_name: Mapped[str] = mapped_column(String(512), nullable=False, default="Unknown")
    poster_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    fanart_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    last_checked: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    initialized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    videos: Mapped[list[Video]] = relationship(
        "Video", back_populates="source", cascade="all, delete-orphan"
    )


class Video(Base):
    __tablename__ = "videos"
    __table_args__ = (UniqueConstraint("video_id", name="uq_videos_video_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("monitored_sources.id", ondelete="CASCADE"))
    video_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="Untitled")
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=VideoStatus.SEEN.value)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    source: Mapped[MonitoredSource] = relationship("MonitoredSource", back_populates="videos")
    jobs: Mapped[list[DownloadJob]] = relationship(
        "DownloadJob", back_populates="video", cascade="all, delete-orphan"
    )


class DownloadJob(Base):
    __tablename__ = "download_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"))
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    video: Mapped[Video] = relationship("Video", back_populates="jobs")
