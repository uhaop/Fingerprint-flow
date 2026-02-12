"""Tests for DJScrewHandler -- DJ Screw detection and album normalization."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.core.dj_screw_handler import DJScrewHandler
from src.models.track import Track


@pytest.fixture
def handler() -> DJScrewHandler:
    mock_archive = MagicMock()
    mock_archive.lookup_chapter_by_title.return_value = None
    mock_fuzzy = MagicMock()
    mock_fuzzy.similarity.return_value = 50.0
    return DJScrewHandler(mock_archive, mock_fuzzy)


class TestIsDJScrewTrack:
    def test_dj_screw_album_artist(self):
        track = Track(file_path=Path("/f.mp3"), album_artist="DJ Screw")
        assert DJScrewHandler.is_dj_screw_track(track) is True

    def test_chapter_album(self):
        track = Track(file_path=Path("/f.mp3"), album="Chapter 051 - Some Title")
        assert DJScrewHandler.is_dj_screw_track(track) is True

    def test_dj_screw_prefix_album(self):
        track = Track(file_path=Path("/f.mp3"), album="DJ Screw - Only Rollin Red")
        assert DJScrewHandler.is_dj_screw_track(track) is True

    def test_normal_track(self):
        track = Track(
            file_path=Path("/f.mp3"),
            artist="Beatles",
            album="Abbey Road",
        )
        assert DJScrewHandler.is_dj_screw_track(track) is False

    def test_folder_path_detection(self):
        track = Track(
            file_path=Path("/Music/DJ Screw/chapter001/track.mp3"),
        )
        assert DJScrewHandler.is_dj_screw_track(track) is True


class TestNormalizeScrewAlbum:
    def test_chapter_with_title(self, handler: DJScrewHandler):
        track = Track(file_path=Path("/f.mp3"), album="Chapter 51 - 9 Fo Shit")
        handler.normalize_screw_album(track)
        assert "Chapter 051" in track.album
        assert "DJ Screw" in track.album_artist

    def test_dj_screw_prefix_chapter(self, handler: DJScrewHandler):
        track = Track(file_path=Path("/f.mp3"), album="DJ Screw - Chapter 22 - Leanin on a Switch")
        handler.normalize_screw_album(track)
        assert "Chapter 022" in track.album
        assert "DJ Screw" in track.album_artist

    def test_doto_prefix(self, handler: DJScrewHandler):
        track = Track(file_path=Path("/f.mp3"), album="D.O.T.O. (Chapter 51 - 9 Fo Shit)")
        handler.normalize_screw_album(track)
        assert "Chapter 051" in track.album

    def test_diary_prefix(self, handler: DJScrewHandler):
        track = Track(
            file_path=Path("/f.mp3"),
            album="Diary of the Originator: Chapter 10 - Southside Still Holdin",
        )
        handler.normalize_screw_album(track)
        assert "Chapter 010" in track.album

    def test_non_screw_album_unchanged(self, handler: DJScrewHandler):
        track = Track(file_path=Path("/f.mp3"), album="Abbey Road")
        handler.normalize_screw_album(track)
        assert track.album == "Abbey Road"

    def test_empty_album(self, handler: DJScrewHandler):
        track = Track(file_path=Path("/f.mp3"), album="")
        handler.normalize_screw_album(track)
        assert track.album == ""

    def test_dj_screw_non_chapter_tape(self, handler: DJScrewHandler):
        track = Track(file_path=Path("/f.mp3"), album="DJ Screw - Only Rollin Red")
        handler.normalize_screw_album(track)
        assert "DJ Screw" in track.album
        assert "Only Rollin Red" in track.album
