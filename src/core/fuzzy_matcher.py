"""Fuzzy matching for misspelled tags and search queries."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rapidfuzz import fuzz, process

from src.utils.constants import (
    DURATION_FALLOFF_MAX_SECONDS,
    DURATION_TOLERANCE_SECONDS,
    FUZZY_MATCH_THRESHOLD,
)
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.models.match_result import MatchCandidate
    from src.models.track import Track

logger = get_logger("core.fuzzy_matcher")


class FuzzyMatcher:
    """Provides fuzzy string matching for correcting misspelled tags
    and comparing metadata between track info and API results.
    """

    def __init__(self, threshold: int = FUZZY_MATCH_THRESHOLD) -> None:
        """Initialize the fuzzy matcher.

        Args:
            threshold: Minimum score (0-100) for a match to be considered valid.
        """
        self._threshold = threshold

    def similarity(self, str_a: str | None, str_b: str | None) -> float:
        """Calculate the similarity between two strings (0.0 - 100.0).

        Uses a weighted combination of ratio, partial_ratio, and
        token_sort_ratio for robustness against different types of
        misspellings and reorderings.

        Args:
            str_a: First string.
            str_b: Second string.

        Returns:
            Similarity score from 0.0 to 100.0.
        """
        if not str_a or not str_b:
            return 0.0

        a = str_a.strip().lower()
        b = str_b.strip().lower()

        if a == b:
            return 100.0

        # Weighted combination of different fuzzy methods
        ratio = fuzz.ratio(a, b)
        partial = fuzz.partial_ratio(a, b)
        token_sort = fuzz.token_sort_ratio(a, b)

        # Weight: token_sort handles word reordering, partial handles substrings,
        # ratio is the strict baseline
        score = (ratio * 0.4) + (partial * 0.3) + (token_sort * 0.3)
        return score

    def is_match(self, str_a: str | None, str_b: str | None) -> bool:
        """Check if two strings are a fuzzy match above the threshold.

        Args:
            str_a: First string.
            str_b: Second string.

        Returns:
            True if similarity is above the configured threshold.
        """
        return self.similarity(str_a, str_b) >= self._threshold

    def best_match(
        self,
        query: str,
        choices: list[str],
        limit: int = 1,
    ) -> list[tuple[str, float]]:
        """Find the best fuzzy matches for a query from a list of choices.

        Args:
            query: The string to match.
            choices: List of candidate strings.
            limit: Maximum number of results to return.

        Returns:
            List of (matched_string, score) tuples, sorted by score descending.
        """
        if not query or not choices:
            return []

        results = process.extract(
            query.strip().lower(),
            [c.strip().lower() for c in choices],
            scorer=fuzz.token_sort_ratio,
            limit=limit,
        )

        # Map back to original case from choices
        matched = []
        for _match_str, score, idx in results:
            if score >= self._threshold:
                matched.append((choices[idx], score))

        return matched

    def compare_track_to_candidate(
        self,
        track: Track,
        candidate: MatchCandidate,
    ) -> dict[str, float]:
        """Compare a track's existing tags against a match candidate.

        Args:
            track: Track with existing tag data.
            candidate: Candidate metadata from an API.

        Returns:
            Dictionary with similarity scores for each compared field:
            - 'title': title similarity (0-100)
            - 'artist': artist similarity (0-100)
            - 'album': album similarity (0-100)
            - 'duration': 100.0 if within tolerance, scaled down otherwise
        """
        scores: dict[str, float] = {}

        # Title similarity
        scores["title"] = self.similarity(track.title, candidate.title)

        # Artist similarity
        scores["artist"] = self.similarity(track.artist, candidate.artist)

        # Album similarity
        scores["album"] = self.similarity(track.album, candidate.album)

        # Duration comparison
        if track.duration is not None and candidate.duration is not None:
            diff = abs(track.duration - candidate.duration)
            if diff <= DURATION_TOLERANCE_SECONDS:
                scores["duration"] = 100.0
            elif diff <= DURATION_FALLOFF_MAX_SECONDS:
                # Linear falloff from 100 to 0 between tolerance and max
                falloff_range = DURATION_FALLOFF_MAX_SECONDS - DURATION_TOLERANCE_SECONDS
                scores["duration"] = max(
                    0.0, 100.0 * (1.0 - (diff - DURATION_TOLERANCE_SECONDS) / falloff_range)
                )
            else:
                scores["duration"] = 0.0
        else:
            # If we can't compare duration, give a neutral score
            scores["duration"] = 50.0

        return scores

    def clean_tag(self, value: str | None) -> str | None:
        """Clean up a tag value by removing common noise.

        Strips extra whitespace, removes "feat." variations from artist names
        for better matching, etc.

        Args:
            value: Raw tag value.

        Returns:
            Cleaned string, or None.
        """
        if not value:
            return None

        cleaned = value.strip()

        # Collapse multiple spaces (single-pass)
        cleaned = " ".join(cleaned.split())

        return cleaned if cleaned else None
