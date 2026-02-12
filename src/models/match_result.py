"""Match result models for metadata lookup results."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MatchCandidate:
    """A single metadata match candidate from an API lookup.

    Attributes:
        title: Track title from the API.
        artist: Artist name from the API.
        album: Album name from the API.
        album_artist: Album artist from the API.
        track_number: Track number within the album.
        total_tracks: Total tracks in the album.
        disc_number: Disc number.
        total_discs: Total discs.
        year: Release year.
        genre: Genre (if available).
        duration: Duration in seconds (from API).
        musicbrainz_recording_id: MusicBrainz recording MBID.
        musicbrainz_release_id: MusicBrainz release MBID.
        cover_art_url: URL to album cover art.
        source: Which API this result came from (e.g. 'musicbrainz', 'discogs').
        source_id: ID within the source system.
        fingerprint_score: Raw fingerprint match score (0.0-1.0) from AcoustID.
        confidence: Calculated overall confidence score (0.0-100.0).
    """

    title: str = ""
    artist: str = ""
    album: str = ""
    album_artist: str = ""
    track_number: int | None = None
    total_tracks: int | None = None
    disc_number: int | None = None
    total_discs: int | None = None
    year: int | None = None
    genre: str | None = None
    duration: float | None = None

    musicbrainz_recording_id: str | None = None
    musicbrainz_release_id: str | None = None
    cover_art_url: str | None = None

    source: str = ""
    source_id: str | None = None
    fingerprint_score: float = 0.0
    confidence: float = 0.0

    @property
    def display_label(self) -> str:
        """Human-readable label for display in the UI."""
        parts = []
        if self.artist:
            parts.append(self.artist)
        if self.title:
            parts.append(f'"{self.title}"')
        if self.album:
            parts.append(f"from {self.album}")
        if self.year:
            parts.append(f"({self.year})")
        return " - ".join(parts) if parts else "(Unknown)"


@dataclass
class MatchResult:
    """Aggregated match results for a single track.

    Contains the ordered list of candidates and the best match selection.

    Attributes:
        candidates: List of match candidates, ordered by confidence (highest first).
        best_match_index: Index of the selected/best candidate, or None.
        acoustid_id: AcoustID identifier that was used for the lookup.
        lookup_source: Primary source used for the lookup ('fingerprint' or 'fuzzy').
    """

    candidates: list[MatchCandidate] = field(default_factory=list)
    best_match_index: int | None = None
    acoustid_id: str | None = None
    lookup_source: str = ""

    @property
    def best_match(self) -> MatchCandidate | None:
        """Return the best match candidate, or None if no candidates exist."""
        if self.best_match_index is not None and self.candidates:
            return self.candidates[self.best_match_index]
        if self.candidates:
            return self.candidates[0]
        return None

    @property
    def top_candidates(self) -> list[MatchCandidate]:
        """Return top 3 candidates for review UI display."""
        return self.candidates[:3]

    @property
    def has_match(self) -> bool:
        """Check if there is at least one candidate."""
        return len(self.candidates) > 0

    @property
    def best_confidence(self) -> float:
        """Return the highest confidence score, or 0.0."""
        if self.candidates:
            return max(c.confidence for c in self.candidates)
        return 0.0
