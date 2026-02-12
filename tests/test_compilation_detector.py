"""Tests for CompilationDetector -- compilation and DJ detection logic."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.models.track import Track
from src.core.compilation_detector import CompilationDetector
from src.core.dj_screw_handler import DJScrewHandler


@pytest.fixture
def detector() -> CompilationDetector:
    """Create a CompilationDetector with a mocked DJScrewHandler."""
    mock_archive = MagicMock()
    mock_fuzzy = MagicMock()
    screw_handler = DJScrewHandler(mock_archive, mock_fuzzy)
    return CompilationDetector(screw_handler)


class TestCompilationDetection:
    def test_various_artists(self, detector: CompilationDetector):
        track = Track(
            file_path=Path("/fake.mp3"),
            album_artist="Various Artists",
        )
        detector.detect(track)
        assert track.is_compilation is True
        assert track.album_artist == "Various Artists"

    def test_dj_album_artist(self, detector: CompilationDetector):
        track = Track(
            file_path=Path("/fake.mp3"),
            artist="Some Rapper",
            album_artist="DJ Mixtape",
        )
        detector.detect(track)
        assert track.is_compilation is True

    def test_compilation_in_album_name(self, detector: CompilationDetector):
        track = Track(
            file_path=Path("/fake.mp3"),
            album="Greatest Hits Compilation",
        )
        detector.detect(track)
        assert track.is_compilation is True

    def test_soundtrack_album(self, detector: CompilationDetector):
        track = Track(
            file_path=Path("/fake.mp3"),
            album="Movie Soundtrack",
        )
        detector.detect(track)
        assert track.is_compilation is True

    def test_normal_album_not_compilation(self, detector: CompilationDetector):
        track = Track(
            file_path=Path("/fake.mp3"),
            artist="Band Name",
            album="Studio Album",
            album_artist="Band Name",
        )
        detector.detect(track)
        assert track.is_compilation is False

    def test_doto_album(self, detector: CompilationDetector):
        track = Track(
            file_path=Path("/fake.mp3"),
            album="D.O.T.O. Something",
        )
        detector.detect(track)
        assert track.is_compilation is True


class TestAlbumLooksLikeCompilation:
    def test_dj_prefix(self):
        assert CompilationDetector.album_looks_like_compilation("DJ Mix Vol 1") is True

    def test_chapter_pattern(self):
        assert CompilationDetector.album_looks_like_compilation("Chapter 051 - Some Title") is True

    def test_bootleg(self):
        assert CompilationDetector.album_looks_like_compilation("Bootleg Tape") is True

    def test_normal_album(self):
        assert CompilationDetector.album_looks_like_compilation("Abbey Road") is False

    def test_empty_string(self):
        assert CompilationDetector.album_looks_like_compilation("") is False

    def test_none(self):
        # Should not crash
        assert CompilationDetector.album_looks_like_compilation(None) is False
