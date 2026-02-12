"""Tests for FuzzyMatcher -- similarity scoring, matching, and tag cleaning."""

from __future__ import annotations

import pytest

from src.core.fuzzy_matcher import FuzzyMatcher
from src.models.track import Track
from src.models.match_result import MatchCandidate


@pytest.fixture
def matcher() -> FuzzyMatcher:
    return FuzzyMatcher(threshold=60)


# ------------------------------------------------------------------
# similarity tests
# ------------------------------------------------------------------


class TestSimilarity:
    def test_identical_strings(self, matcher: FuzzyMatcher):
        assert matcher.similarity("Hello World", "Hello World") == 100.0

    def test_case_insensitive(self, matcher: FuzzyMatcher):
        assert matcher.similarity("hello world", "HELLO WORLD") == 100.0

    def test_empty_strings(self, matcher: FuzzyMatcher):
        assert matcher.similarity("", "hello") == 0.0
        assert matcher.similarity("hello", "") == 0.0
        assert matcher.similarity("", "") == 0.0

    def test_none_values(self, matcher: FuzzyMatcher):
        assert matcher.similarity(None, "hello") == 0.0
        assert matcher.similarity("hello", None) == 0.0
        assert matcher.similarity(None, None) == 0.0

    def test_similar_strings(self, matcher: FuzzyMatcher):
        score = matcher.similarity("Runnin' (Dying to Live)", "Runnin (Dying To Live)")
        assert score > 80.0

    def test_completely_different(self, matcher: FuzzyMatcher):
        score = matcher.similarity("AAAA", "ZZZZZZZZZZ")
        assert score < 30.0

    def test_whitespace_handling(self, matcher: FuzzyMatcher):
        score = matcher.similarity("  hello   world  ", "hello world")
        assert score > 90.0

    def test_word_reordering(self, matcher: FuzzyMatcher):
        """Token sort ratio should handle word reordering."""
        score = matcher.similarity("World Hello", "Hello World")
        assert score > 60.0

    def test_partial_match(self, matcher: FuzzyMatcher):
        """Partial ratio should handle substring matching."""
        score = matcher.similarity("Thriller", "Thriller (Special Edition)")
        assert score > 55.0


# ------------------------------------------------------------------
# is_match tests
# ------------------------------------------------------------------


class TestIsMatch:
    def test_above_threshold(self, matcher: FuzzyMatcher):
        assert matcher.is_match("Hello World", "Hello World") is True

    def test_below_threshold(self, matcher: FuzzyMatcher):
        assert matcher.is_match("AAAA", "ZZZZZZZZZZ") is False

    def test_near_threshold(self):
        """Low threshold should match loosely."""
        loose = FuzzyMatcher(threshold=20)
        assert loose.is_match("abc", "abcdef") is True

    def test_high_threshold(self):
        """High threshold should reject almost-matches."""
        strict = FuzzyMatcher(threshold=99)
        assert strict.is_match("Hello Worl", "Hello World") is False


# ------------------------------------------------------------------
# best_match tests
# ------------------------------------------------------------------


class TestBestMatch:
    def test_finds_correct_match(self, matcher: FuzzyMatcher):
        choices = ["Stairway to Heaven", "Bohemian Rhapsody", "Hotel California"]
        result = matcher.best_match("Bohemien Rapsody", choices)
        assert len(result) >= 1
        assert result[0][0] == "Bohemian Rhapsody"

    def test_empty_query(self, matcher: FuzzyMatcher):
        assert matcher.best_match("", ["a", "b"]) == []

    def test_empty_choices(self, matcher: FuzzyMatcher):
        assert matcher.best_match("hello", []) == []

    def test_multiple_results(self, matcher: FuzzyMatcher):
        choices = ["Song A", "Song B", "Song C", "Different Thing"]
        results = matcher.best_match("Song", choices, limit=3)
        assert len(results) >= 1
        # All results should be Song-like
        for name, score in results:
            assert "Song" in name or score >= 60


# ------------------------------------------------------------------
# compare_track_to_candidate tests
# ------------------------------------------------------------------


class TestCompareTrackToCandidate:
    def test_perfect_match(self, matcher: FuzzyMatcher):
        track = Track(
            file_path="/fake.mp3",
            title="My Song",
            artist="The Artist",
            album="The Album",
            duration=240.0,
        )
        candidate = MatchCandidate(
            title="My Song",
            artist="The Artist",
            album="The Album",
            duration=240.0,
            source="test",
        )
        scores = matcher.compare_track_to_candidate(track, candidate)
        assert scores["title"] == 100.0
        assert scores["artist"] == 100.0
        assert scores["album"] == 100.0
        assert scores["duration"] == 100.0

    def test_duration_within_tolerance(self, matcher: FuzzyMatcher):
        track = Track(file_path="/f.mp3", title="X", duration=240.0)
        candidate = MatchCandidate(title="X", duration=241.5, source="test")
        scores = matcher.compare_track_to_candidate(track, candidate)
        assert scores["duration"] == 100.0

    def test_duration_outside_max(self, matcher: FuzzyMatcher):
        track = Track(file_path="/f.mp3", title="X", duration=240.0)
        candidate = MatchCandidate(title="X", duration=500.0, source="test")
        scores = matcher.compare_track_to_candidate(track, candidate)
        assert scores["duration"] == 0.0

    def test_no_duration(self, matcher: FuzzyMatcher):
        track = Track(file_path="/f.mp3", title="X")
        candidate = MatchCandidate(title="X", source="test")
        scores = matcher.compare_track_to_candidate(track, candidate)
        assert scores["duration"] == 50.0  # Neutral


# ------------------------------------------------------------------
# clean_tag tests
# ------------------------------------------------------------------


class TestCleanTag:
    def test_strips_whitespace(self, matcher: FuzzyMatcher):
        assert matcher.clean_tag("  hello  ") == "hello"

    def test_collapses_spaces(self, matcher: FuzzyMatcher):
        assert matcher.clean_tag("hello    world") == "hello world"

    def test_none_returns_none(self, matcher: FuzzyMatcher):
        assert matcher.clean_tag(None) is None

    def test_empty_string_returns_none(self, matcher: FuzzyMatcher):
        assert matcher.clean_tag("") is None

    def test_only_spaces_returns_none(self, matcher: FuzzyMatcher):
        assert matcher.clean_tag("     ") is None

    def test_normal_string_unchanged(self, matcher: FuzzyMatcher):
        assert matcher.clean_tag("Normal Tag") == "Normal Tag"
