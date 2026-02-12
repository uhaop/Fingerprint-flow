"""Tests for src/utils/file_utils.py -- safe file operations and filename sanitization."""

from pathlib import Path

import pytest

from src.utils.file_utils import (
    enforce_path_length,
    get_file_size_mb,
    is_audio_file,
    normalize_artist_name,
    safe_copy,
    safe_move,
    sanitize_filename,
    smart_title_case,
    unique_path,
)

# ---------------------------------------------------------------------------
# sanitize_filename
# ---------------------------------------------------------------------------


class TestSanitizeFilename:
    """Tests for sanitize_filename()."""

    def test_removes_invalid_characters(self):
        assert sanitize_filename('song<>:"/\\|?*.mp3') == "song_.mp3"

    def test_strips_leading_trailing_dots_and_spaces(self):
        assert sanitize_filename("...hello...") == "hello"
        assert sanitize_filename("  hello  ") == "hello"

    def test_collapses_multiple_underscores(self):
        assert sanitize_filename("a__b___c") == "a_b_c"

    def test_returns_unknown_for_empty(self):
        assert sanitize_filename("") == "Unknown"
        assert sanitize_filename("...") == "Unknown"

    def test_normal_string_unchanged(self):
        assert sanitize_filename("My Song Title") == "My Song Title"

    def test_windows_reserved_names(self):
        """Windows reserved device names must be prefixed to avoid errors."""
        assert sanitize_filename("CON") == "_CON"
        assert sanitize_filename("con") == "_con"
        assert sanitize_filename("PRN") == "_PRN"
        assert sanitize_filename("AUX") == "_AUX"
        assert sanitize_filename("NUL") == "_NUL"
        assert sanitize_filename("COM1") == "_COM1"
        assert sanitize_filename("COM9") == "_COM9"
        assert sanitize_filename("LPT1") == "_LPT1"
        assert sanitize_filename("LPT9") == "_LPT9"
        # "CON.txt" (with extension) is also reserved
        assert sanitize_filename("CON.mp3") == "_CON.mp3"

    def test_non_reserved_similar_names(self):
        """Names that look like reserved names but aren't should be unchanged."""
        assert sanitize_filename("CONSOLE") == "CONSOLE"
        assert sanitize_filename("COM10") == "COM10"
        assert sanitize_filename("CONNECT") == "CONNECT"

    def test_max_component_length(self):
        """Very long filenames are truncated."""
        long_name = "A" * 300
        result = sanitize_filename(long_name)
        assert len(result) <= 240

    def test_unicode_preserved(self):
        assert sanitize_filename("Caf\u00e9 del Mar") == "Caf\u00e9 del Mar"


# ---------------------------------------------------------------------------
# safe_copy
# ---------------------------------------------------------------------------


class TestSafeCopy:
    """Tests for safe_copy()."""

    def test_copies_file(self, tmp_path):
        src = tmp_path / "source.txt"
        src.write_text("hello")
        dst = tmp_path / "subdir" / "dest.txt"

        result = safe_copy(src, dst)

        assert result == dst
        assert dst.read_text() == "hello"
        assert src.exists()  # Source is not deleted

    def test_creates_parent_directories(self, tmp_path):
        src = tmp_path / "source.txt"
        src.write_text("data")
        dst = tmp_path / "a" / "b" / "c" / "dest.txt"

        safe_copy(src, dst)

        assert dst.exists()

    def test_raises_on_missing_source(self, tmp_path):
        src = tmp_path / "nonexistent.txt"
        dst = tmp_path / "dest.txt"

        with pytest.raises(FileNotFoundError):
            safe_copy(src, dst)


# ---------------------------------------------------------------------------
# safe_move
# ---------------------------------------------------------------------------


class TestSafeMove:
    """Tests for safe_move()."""

    def test_moves_file(self, tmp_path):
        src = tmp_path / "source.txt"
        src.write_text("hello")
        dst = tmp_path / "dest.txt"

        result = safe_move(src, dst)

        assert result == dst
        assert dst.read_text() == "hello"
        assert not src.exists()  # Source is gone

    def test_creates_parent_directories(self, tmp_path):
        src = tmp_path / "source.txt"
        src.write_text("data")
        dst = tmp_path / "a" / "b" / "dest.txt"

        safe_move(src, dst)

        assert dst.exists()
        assert not src.exists()

    def test_raises_on_missing_source(self, tmp_path):
        src = tmp_path / "nonexistent.txt"
        dst = tmp_path / "dest.txt"

        with pytest.raises(FileNotFoundError):
            safe_move(src, dst)

    def test_preserves_file_size(self, tmp_path):
        """After a move, the destination should have the same size as the source."""
        data = b"x" * 10000
        src = tmp_path / "source.bin"
        src.write_bytes(data)
        dst = tmp_path / "dest.bin"

        safe_move(src, dst)

        assert dst.stat().st_size == len(data)


# ---------------------------------------------------------------------------
# unique_path
# ---------------------------------------------------------------------------


class TestUniquePath:
    """Tests for unique_path()."""

    def test_returns_original_if_no_collision(self, tmp_path):
        path = tmp_path / "song.mp3"
        assert unique_path(path) == path

    def test_appends_counter_on_collision(self, tmp_path):
        path = tmp_path / "song.mp3"
        path.write_text("existing")

        result = unique_path(path)
        assert result == tmp_path / "song (1).mp3"

    def test_increments_counter(self, tmp_path):
        path = tmp_path / "song.mp3"
        path.write_text("existing")
        (tmp_path / "song (1).mp3").write_text("existing")
        (tmp_path / "song (2).mp3").write_text("existing")

        result = unique_path(path)
        assert result == tmp_path / "song (3).mp3"


# ---------------------------------------------------------------------------
# enforce_path_length
# ---------------------------------------------------------------------------


class TestEnforcePathLength:
    """Tests for enforce_path_length()."""

    def test_short_path_unchanged(self):
        path = Path("/music/Artist/Album/01 - Song.mp3")
        assert enforce_path_length(path, max_length=260) == path

    def test_long_path_truncated(self):
        long_title = "A" * 200
        path = Path(f"/music/Artist/Album/{long_title}.mp3")
        result = enforce_path_length(path, max_length=100)
        assert len(str(result)) <= 100

    def test_extension_preserved(self):
        long_title = "A" * 300
        path = Path(f"/music/Artist/Album/{long_title}.flac")
        result = enforce_path_length(path, max_length=100)
        assert str(result).endswith(".flac")


# ---------------------------------------------------------------------------
# is_audio_file
# ---------------------------------------------------------------------------


class TestIsAudioFile:
    """Tests for is_audio_file()."""

    @pytest.mark.parametrize(
        "ext",
        [
            ".mp3",
            ".flac",
            ".m4a",
            ".aac",
            ".ogg",
            ".opus",
            ".wma",
            ".aiff",
            ".aif",
            ".wav",
            ".ape",
            ".wv",
        ],
    )
    def test_supported_formats(self, ext):
        assert is_audio_file(Path(f"song{ext}")) is True

    @pytest.mark.parametrize(
        "ext",
        [
            ".txt",
            ".jpg",
            ".pdf",
            ".exe",
            ".doc",
            ".zip",
        ],
    )
    def test_unsupported_formats(self, ext):
        assert is_audio_file(Path(f"file{ext}")) is False

    def test_case_insensitive(self):
        assert is_audio_file(Path("song.MP3")) is True
        assert is_audio_file(Path("song.Flac")) is True


# ---------------------------------------------------------------------------
# smart_title_case
# ---------------------------------------------------------------------------


class TestSmartTitleCase:
    """Tests for smart_title_case()."""

    def test_basic_title_case(self):
        assert smart_title_case("hello world") == "Hello World"

    def test_small_words_lowercase(self):
        result = smart_title_case("the art of war")
        assert result == "The Art of War"

    def test_first_word_always_capitalized(self):
        assert smart_title_case("the quick brown fox").startswith("The")

    def test_known_abbreviations_uppercase(self):
        result = smart_title_case("dj screw ft mc something")
        assert "DJ" in result
        assert "MC" in result
        assert "FT" in result

    def test_empty_string(self):
        assert smart_title_case("") == ""

    def test_known_artist_override(self):
        assert smart_title_case("2pac") == "2Pac"
        assert smart_title_case("outkast") == "OutKast"


# ---------------------------------------------------------------------------
# normalize_artist_name
# ---------------------------------------------------------------------------


class TestNormalizeArtistName:
    """Tests for normalize_artist_name()."""

    def test_known_override(self):
        assert normalize_artist_name("dj screw") == "DJ Screw"
        assert normalize_artist_name("2pac") == "2Pac"

    def test_unknown_artist_title_cased(self):
        assert normalize_artist_name("john doe") == "John Doe"

    def test_empty_string(self):
        assert normalize_artist_name("") == ""

    def test_none(self):
        assert normalize_artist_name(None) is None


# ---------------------------------------------------------------------------
# get_file_size_mb
# ---------------------------------------------------------------------------


class TestGetFileSizeMb:
    """Tests for get_file_size_mb()."""

    def test_returns_size(self, tmp_path):
        path = tmp_path / "file.bin"
        path.write_bytes(b"x" * (1024 * 1024))  # 1 MB
        assert abs(get_file_size_mb(path) - 1.0) < 0.01

    def test_returns_zero_for_missing(self, tmp_path):
        assert get_file_size_mb(tmp_path / "missing.bin") == 0.0
