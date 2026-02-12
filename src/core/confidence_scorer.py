"""Confidence scoring algorithm for match quality assessment."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.core.fuzzy_matcher import FuzzyMatcher
from src.utils.constants import (
    ALBUM_SIMILARITY_THRESHOLD,
    DEFAULT_AUTO_APPLY_THRESHOLD,
    DEFAULT_REVIEW_THRESHOLD,
    WEIGHT_ALBUM_CONSISTENCY,
    WEIGHT_ARTIST,
    WEIGHT_DURATION,
    WEIGHT_FINGERPRINT,
    WEIGHT_TITLE,
)
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.models.match_result import MatchCandidate, MatchResult
    from src.models.track import Track

logger = get_logger("core.confidence_scorer")


class ConfidenceScorer:
    """Calculates confidence scores for metadata match candidates.

    Scoring is based on multiple weighted factors:
    - Fingerprint match score (40%)
    - Title similarity (20%)
    - Artist similarity (20%)
    - Duration match (10%)
    - Album consistency (10%)

    Thresholds:
    - 90-100: Auto-apply
    - 70-89: Show top picks for user review
    - Below 70: Manual review
    """

    def __init__(
        self,
        auto_threshold: float = DEFAULT_AUTO_APPLY_THRESHOLD,
        review_threshold: float = DEFAULT_REVIEW_THRESHOLD,
    ) -> None:
        """Initialize the confidence scorer.

        Args:
            auto_threshold: Confidence above which matches are auto-applied.
            review_threshold: Confidence above which top picks are shown.
        """
        self._auto_threshold = auto_threshold
        self._review_threshold = review_threshold
        self._fuzzy = FuzzyMatcher()

    def score_candidate(
        self,
        track: Track,
        candidate: MatchCandidate,
        album_tracks: list[Track] | None = None,
    ) -> float:
        """Calculate the overall confidence score for a single candidate.

        Args:
            track: The original track with existing tag data.
            candidate: A match candidate from an API lookup.
            album_tracks: Optional list of other tracks in the same batch
                (used for album consistency scoring).

        Returns:
            Confidence score from 0.0 to 100.0.
        """
        # Compare track tags to candidate
        field_scores = self._fuzzy.compare_track_to_candidate(track, candidate)

        # Fingerprint score (already 0.0-1.0 from AcoustID, scale to 0-100)
        fingerprint_score = candidate.fingerprint_score * 100.0

        # Title similarity
        title_score = field_scores.get("title", 0.0)

        # Artist similarity
        artist_score = field_scores.get("artist", 0.0)

        # Duration match
        duration_score = field_scores.get("duration", 50.0)

        # Album consistency: check if other tracks in the batch match the same album
        album_score = self._calculate_album_consistency(candidate, album_tracks)

        # Weighted combination
        overall = (
            fingerprint_score * WEIGHT_FINGERPRINT
            + title_score * WEIGHT_TITLE
            + artist_score * WEIGHT_ARTIST
            + duration_score * WEIGHT_DURATION
            + album_score * WEIGHT_ALBUM_CONSISTENCY
        )

        # Clamp to 0-100
        overall = max(0.0, min(100.0, overall))

        logger.debug(
            "Score for '%s' -> '%s - %s': fp=%.1f, title=%.1f, artist=%.1f, "
            "dur=%.1f, album=%.1f => overall=%.1f",
            track.display_title,
            candidate.artist,
            candidate.title,
            fingerprint_score,
            title_score,
            artist_score,
            duration_score,
            album_score,
            overall,
        )

        return overall

    def score_match_result(
        self,
        track: Track,
        match_result: MatchResult,
        album_tracks: list[Track] | None = None,
    ) -> MatchResult:
        """Score all candidates in a MatchResult and sort by confidence.

        Args:
            track: The original track.
            match_result: MatchResult containing candidates to score.
            album_tracks: Optional list of batch tracks for album consistency.

        Returns:
            The same MatchResult with candidates scored and sorted.
        """
        for candidate in match_result.candidates:
            candidate.confidence = self.score_candidate(track, candidate, album_tracks)

        # Sort by confidence descending
        match_result.candidates.sort(key=lambda c: c.confidence, reverse=True)

        # Set best match to the highest confidence candidate
        if match_result.candidates:
            match_result.best_match_index = 0

        return match_result

    def classify(self, confidence: float) -> str:
        """Classify a confidence score into an action category.

        Args:
            confidence: Score from 0-100.

        Returns:
            One of: 'auto_apply', 'review_top_picks', 'manual_review', 'unmatched'.
        """
        if confidence >= self._auto_threshold:
            return "auto_apply"
        elif confidence >= self._review_threshold:
            return "review_top_picks"
        elif confidence > 0:
            return "manual_review"
        else:
            return "unmatched"

    def _calculate_album_consistency(
        self,
        candidate: MatchCandidate,
        album_tracks: list[Track] | None,
    ) -> float:
        """Check if other tracks in the batch appear to be from the same album.

        If multiple tracks are being processed together and this candidate's
        album matches what other tracks were identified as, that's a strong
        signal the match is correct.

        Args:
            candidate: The candidate to check.
            album_tracks: Other tracks in the batch.

        Returns:
            Score from 0.0 to 100.0.
        """
        if not album_tracks or not candidate.album:
            # No context to compare -- return a neutral score
            return 50.0

        matches = 0
        total = 0

        for other_track in album_tracks:
            if other_track.album:
                total += 1
                sim = self._fuzzy.similarity(candidate.album, other_track.album)
                if sim >= ALBUM_SIMILARITY_THRESHOLD:
                    matches += 1

        if total == 0:
            return 50.0

        # Score based on fraction of matching albums
        return (matches / total) * 100.0
