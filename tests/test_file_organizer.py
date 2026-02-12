"""Tests for FileOrganizer -- destination building, organization, rollback."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from src.models.track import Track
from src.core.file_organizer import FileOrganizer


@pytest.fixture
def tmp_lib(tmp_path: Path) -> Path:
    """Return a temporary library root directory."""
    lib = tmp_path / "library"
    lib.mkdir()
    return lib


@pytest.fixture
def organizer(tmp_lib: Path) -> FileOrganizer:
    """Return a FileOrganizer pointed at the temp library."""
    return FileOrganizer(
        library_path=tmp_lib,
        backup_path=tmp_lib / "_Backups",
        keep_originals=True,
    )


def _make_audio_file(tmp_path: Path, name: str = "test.mp3") -> Path:
    """Create a dummy audio file for testing."""
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\x00" * 128)
    return p


# ------------------------------------------------------------------
# _build_destination tests
# ------------------------------------------------------------------


class TestBuildDestination:
    """Tests for the destination path calculation."""

    def test_standard_album(self, organizer: FileOrganizer, tmp_lib: Path):
        track = Track(
            file_path=Path("/fake/song.mp3"),
            title="My Song",
            artist="The Artist",
            album="Great Album",
            year=2024,
            track_number=3,
        )
        dest = organizer.preview_destination(track)
        assert dest == tmp_lib / "The Artist" / "Great Album (2024)" / "03 - My Song.mp3"

    def test_no_album_goes_to_singles(self, organizer: FileOrganizer, tmp_lib: Path):
        track = Track(
            file_path=Path("/fake/single.mp3"),
            title="Standalone",
            artist="Solo Artist",
        )
        dest = organizer.preview_destination(track)
        assert dest == tmp_lib / "Solo Artist" / "Singles" / "Standalone.mp3"

    def test_compilation_uses_album_artist(self, organizer: FileOrganizer, tmp_lib: Path):
        track = Track(
            file_path=Path("/fake/comp.mp3"),
            title="Track Title",
            artist="Featured Artist",
            album="DJ Mix Vol 1",
            album_artist="DJ Someone",
            year=2023,
            track_number=1,
            is_compilation=True,
        )
        dest = organizer.preview_destination(track)
        # Compilation: folder uses album_artist, filename includes track artist
        assert "DJ Someone" in str(dest)
        assert "Featured Artist" in dest.name

    def test_multi_disc_album(self, organizer: FileOrganizer, tmp_lib: Path):
        track = Track(
            file_path=Path("/fake/disc2.mp3"),
            title="Song on Disc 2",
            artist="Band",
            album="Double Album",
            year=2020,
            track_number=5,
            disc_number=2,
            total_discs=2,
        )
        dest = organizer.preview_destination(track)
        assert "Disc 2" in str(dest)

    def test_unknown_year(self, organizer: FileOrganizer, tmp_lib: Path):
        track = Track(
            file_path=Path("/fake/noyear.mp3"),
            title="No Year Song",
            artist="Artist",
            album="Album",
            track_number=1,
        )
        dest = organizer.preview_destination(track)
        assert "Unknown Year" in str(dest)

    def test_no_track_number(self, organizer: FileOrganizer, tmp_lib: Path):
        track = Track(
            file_path=Path("/fake/nonum.mp3"),
            title="No Number",
            artist="Artist",
            album="Album",
            year=2024,
        )
        dest = organizer.preview_destination(track)
        # Without track number, filename should just be the title
        assert dest.stem == "No Number"


# ------------------------------------------------------------------
# organize / rollback tests
# ------------------------------------------------------------------


class TestOrganize:
    """Tests for actual file organization and rollback."""

    def test_organize_moves_file(self, organizer: FileOrganizer, tmp_lib: Path, tmp_path: Path):
        src = _make_audio_file(tmp_path / "input")
        track = Track(
            file_path=src,
            title="Test Song",
            artist="Test Artist",
            album="Test Album",
            year=2024,
            track_number=1,
        )
        result = organizer.organize(track)
        assert result.file_path.exists()
        assert not src.exists()
        assert "Test Artist" in str(result.file_path)
        assert result.file_path.parent.is_dir()

    def test_organize_creates_backup(self, organizer: FileOrganizer, tmp_lib: Path, tmp_path: Path):
        src = _make_audio_file(tmp_path / "input")
        track = Track(
            file_path=src,
            title="Backup Test",
            artist="Artist",
            album="Album",
            year=2024,
            track_number=1,
        )
        organizer.organize(track)
        backup_dir = tmp_lib / "_Backups"
        assert backup_dir.exists()
        backup_files = list(backup_dir.iterdir())
        assert len(backup_files) >= 1

    def test_organize_duplicate_detection(
        self, organizer: FileOrganizer, tmp_lib: Path, tmp_path: Path,
    ):
        """If destination already exists, skip with error message."""
        src1 = _make_audio_file(tmp_path / "input1", "song.mp3")
        track1 = Track(
            file_path=src1, title="Song", artist="Artist",
            album="Album", year=2024, track_number=1,
        )
        organizer.organize(track1)

        # Now try to organize a second file to the same destination
        src2 = _make_audio_file(tmp_path / "input2", "song.mp3")
        track2 = Track(
            file_path=src2, title="Song", artist="Artist",
            album="Album", year=2024, track_number=1,
        )
        result = organizer.organize(track2)
        assert result.error_message and "Duplicate" in result.error_message

    def test_rollback_last(self, organizer: FileOrganizer, tmp_lib: Path, tmp_path: Path):
        src = _make_audio_file(tmp_path / "input")
        original_path = src
        track = Track(
            file_path=src,
            title="Rollback Me",
            artist="Artist",
            album="Album",
            year=2024,
            track_number=1,
        )
        organizer.organize(track)
        assert not original_path.exists()

        # Rollback
        success = organizer.rollback_last()
        assert success
        assert original_path.exists()

    def test_rollback_all(self, organizer: FileOrganizer, tmp_lib: Path, tmp_path: Path):
        tracks = []
        for i in range(3):
            src = _make_audio_file(tmp_path / f"input{i}", f"song{i}.mp3")
            track = Track(
                file_path=src,
                title=f"Song {i}",
                artist="Artist",
                album="Album",
                year=2024,
                track_number=i + 1,
            )
            tracks.append((track, src))

        for track, _ in tracks:
            organizer.organize(track)

        rolled_back = organizer.rollback_all()
        assert rolled_back == 3

        for _, original_path in tracks:
            assert original_path.exists()

    def test_organize_missing_file(self, organizer: FileOrganizer):
        track = Track(
            file_path=Path("/nonexistent/file.mp3"),
            title="Ghost",
            artist="Nobody",
            album="Nowhere",
            year=2024,
            track_number=1,
        )
        result = organizer.organize(track)
        assert result.error_message is not None

    def test_organize_unmatched(self, organizer: FileOrganizer, tmp_lib: Path, tmp_path: Path):
        src = _make_audio_file(tmp_path / "input")
        track = Track(file_path=src)
        result = organizer.organize_unmatched(track)
        assert "_Unmatched" in str(result.file_path)
        assert result.file_path.exists()


# ------------------------------------------------------------------
# Safety tests
# ------------------------------------------------------------------


class TestSafety:
    """Tests for data safety guarantees."""

    def test_backup_before_changes_creates_backup(
        self, organizer: FileOrganizer, tmp_lib: Path, tmp_path: Path,
    ):
        """backup_before_changes() should create an unmodified backup."""
        src = _make_audio_file(tmp_path / "input", "song.mp3")
        original_data = src.read_bytes()
        track = Track(file_path=src)

        backup_path = organizer.backup_before_changes(track)

        assert backup_path is not None
        assert backup_path.exists()
        # Backup must have the original data
        assert backup_path.read_bytes() == original_data

    def test_backup_before_changes_reused_by_organize(
        self, organizer: FileOrganizer, tmp_lib: Path, tmp_path: Path,
    ):
        """If backup_before_changes was called, organize() should not create a second backup."""
        src = _make_audio_file(tmp_path / "input", "song.mp3")
        track = Track(
            file_path=src, title="Song", artist="Artist",
            album="Album", year=2024, track_number=1,
        )

        # Pre-backup
        organizer.backup_before_changes(track)

        # Organize (should reuse the pre-backup)
        organizer.organize(track)

        backup_dir = tmp_lib / "_Backups"
        backup_files = list(backup_dir.iterdir())
        # Should be exactly 1 backup, not 2
        assert len(backup_files) == 1

    def test_no_cleanup_outside_library(
        self, tmp_lib: Path, tmp_path: Path,
    ):
        """Cleanup must never delete directories outside the library."""
        organizer = FileOrganizer(library_path=tmp_lib, keep_originals=False)

        # Create a source directory OUTSIDE the library with a file
        external_dir = tmp_path / "external" / "subfolder"
        external_dir.mkdir(parents=True)
        src = external_dir / "song.mp3"
        src.write_bytes(b"\x00" * 128)

        track = Track(
            file_path=src, title="Song", artist="Artist",
            album="Album", year=2024, track_number=1,
        )
        organizer.organize(track)

        # The external directory should still exist (not cleaned up)
        assert (tmp_path / "external").exists()

    def test_dry_run_does_not_move_files(
        self, tmp_lib: Path, tmp_path: Path,
    ):
        """In dry-run mode, files must not be moved or modified."""
        organizer = FileOrganizer(
            library_path=tmp_lib, keep_originals=True, dry_run=True,
        )
        src = _make_audio_file(tmp_path / "input", "song.mp3")
        original_data = src.read_bytes()
        track = Track(
            file_path=src, title="Song", artist="Artist",
            album="Album", year=2024, track_number=1,
        )

        result = organizer.organize(track)

        # The file_path should be updated to the would-be destination
        assert result.file_path != src
        assert "Artist" in str(result.file_path)
        # But the source file should still be in its original location
        assert src.exists()
        assert src.read_bytes() == original_data
        # No backup should be created
        assert not (tmp_lib / "_Backups").exists()

    def test_dry_run_unmatched_does_not_move_files(
        self, tmp_lib: Path, tmp_path: Path,
    ):
        """Dry-run mode for unmatched files must not move them."""
        organizer = FileOrganizer(
            library_path=tmp_lib, keep_originals=True, dry_run=True,
        )
        src = _make_audio_file(tmp_path / "input", "song.mp3")
        track = Track(file_path=src)

        result = organizer.organize_unmatched(track)

        assert "_Unmatched" in str(result.file_path)
        assert src.exists()  # File should not have moved
