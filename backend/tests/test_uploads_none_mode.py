"""Regression: monitor_mode none must still discover Uploads as SEEN."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import Base  # noqa: E402
from app.models import MonitoredSource, Video, VideoStatus  # noqa: E402
from app.services import monitor, ytdlp  # noqa: E402


class CheckSourceNoneModeDiscovers(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        data = Path(self._tmpdir.name)
        self._cfg_patch = patch(
            "app.services.monitor.get_config",
            return_value=type(
                "Cfg",
                (),
                {
                    "library_root": str(data / "lib"),
                    "music_library_root": str(data / "music"),
                },
            )(),
        )
        self._cfg_patch.start()
        self._engine = create_engine(
            f"sqlite:///{(data / 'test.db').as_posix()}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self._engine)
        self.Session = sessionmaker(bind=self._engine)

    def tearDown(self) -> None:
        self._cfg_patch.stop()
        self._engine.dispose()
        try:
            self._tmpdir.cleanup()
        except PermissionError:
            pass

    def test_none_mode_lists_uploads_as_seen(self) -> None:
        db = self.Session()
        try:
            source = MonitoredSource(
                url="https://www.youtube.com/@barnbrothers/videos",
                title="The Barn Brothers",
                yt_id="UC_test",
                source_type="channel",
                folder_name="The Barn Brothers",
                enabled=False,
                monitor_mode="none",
                quality="",
                media_type="video",
                initialized=False,
            )
            db.add(source)
            db.commit()
            db.refresh(source)

            fake_entries = [
                ytdlp.PlaylistEntry(video_id="vid1", title="One"),
                ytdlp.PlaylistEntry(video_id="vid2", title="Two"),
            ]
            with patch.object(monitor.ytdlp, "list_entries", return_value=fake_entries):
                result = monitor.check_source(db, source, initial=True)

            self.assertEqual(result["entries_seen"], 2)
            self.assertEqual(result["marked_seen"], 2)
            self.assertEqual(result["marked_wanted"], 0)
            videos = db.query(Video).filter(Video.source_id == source.id).all()
            self.assertEqual(len(videos), 2)
            self.assertTrue(all(v.status == VideoStatus.SEEN.value for v in videos))
            db.refresh(source)
            self.assertTrue(source.initialized)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
