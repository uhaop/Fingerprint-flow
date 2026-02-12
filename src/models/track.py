"""Track data model -- represents a single audio file and its metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from src.models.processing_state import ProcessingState


@dataclass
class Track:
    """Represents a single audio file with its metadata and processing state.

    Attributes:
        file_path: Absolute path to the audio file on disk.
        title: Track title (from tags or API).
        artist: Primary artist name.
        album: Album name.
        album_artist: Album artist (may differ from track artist on compilations).
        track_number: Track number within the album.
        total_tracks: Total tracks in the album.
        disc_number: Disc number for multi-disc releases.
        total_discs: Total discs in the release.
        year: Release year.
        genre: Genre tag.
        duration: Duration in seconds (from file metadata).
        fingerprint: Chromaprint audio fingerprint string.
        acoustid: AcoustID identifier.
        musicbrainz_recording_id: MusicBrainz recording MBID.
        musicbrainz_release_id: MusicBrainz release MBID.
        cover_art_url: URL to album cover art.
        cover_art_data: Raw bytes of embedded or downloaded cover art.
        file_format: Audio format (e.g. 'mp3', 'flac').
        file_size_mb: File size in megabytes.
        bitrate: Audio bitrate in kbps (if available).
        sample_rate: Sample rate in Hz (if available).
        state: Current processing state.
        confidence: Overall match confidence score (0.0 - 100.0).
        original_path: Original file path before organization (for rollback).
        error_message: Description of any error encountered during processing.
        original_tags: Snapshot of tag values before matching (for preview diffs).
    """

    # --- Required ---
    file_path: Path

    # --- Metadata (populated during processing) ---
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    album_artist: str | None = None
    track_number: int | None = None
    total_tracks: int | None = None
    disc_number: int | None = None
    total_discs: int | None = None
    year: int | None = None
    genre: str | None = None
    duration: float | None = None

    # --- Identification ---
    fingerprint: str | None = None
    acoustid: str | None = None
    musicbrainz_recording_id: str | None = None
    musicbrainz_release_id: str | None = None

    # --- Cover Art ---
    cover_art_url: str | None = None
    cover_art_data: bytes | None = field(default=None, repr=False)

    # --- File Info ---
    file_format: str | None = None
    file_size_mb: float = 0.0
    bitrate: int | None = None
    sample_rate: int | None = None

    # --- Compilation / Various Artists ---
    is_compilation: bool = False

    # --- Processing State ---
    state: ProcessingState = ProcessingState.PENDING
    confidence: float = 0.0
    original_path: Path | None = None
    error_message: str | None = None

    # --- Original tags snapshot (for before/after preview diffs) ---
    original_tags: dict = field(default_factory=dict, repr=False)

    # --- Database ---
    id: int | None = None

    def __post_init__(self) -> None:
        """Ensure file_path is a Path object and extract format."""
        if isinstance(self.file_path, str):
            self.file_path = Path(self.file_path)
        if self.original_path is None:
            self.original_path = self.file_path
        if self.file_format is None and self.file_path.suffix:
            self.file_format = self.file_path.suffix.lstrip(".").lower()

    @property
    def display_title(self) -> str:
        """Human-readable title, falling back to filename."""
        return self.title or self.file_path.stem

    @property
    def display_artist(self) -> str:
        """Human-readable artist, falling back to 'Unknown Artist'."""
        return self.artist or "Unknown Artist"

    @property
    def display_album(self) -> str:
        """Human-readable album, falling back to 'Unknown Album'."""
        return self.album or "Unknown Album"

    @property
    def has_basic_tags(self) -> bool:
        """Check if the track has at least title and artist tags."""
        return bool(self.title and self.artist)

    @property
    def has_complete_tags(self) -> bool:
        """Check if the track has a full set of tags for organization."""
        return bool(self.title and self.artist and self.album and self.track_number is not None)

    def snapshot_original_tags(self) -> None:
        """Capture the current tag values as the 'original' state.

        Call this right after reading tags from the file and before
        the matching pipeline overwrites fields.  The snapshot powers
        the before/after diff in the Preview Report.
        """
        self.original_tags = {
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "album_artist": self.album_artist,
            "track_number": self.track_number,
            "total_tracks": self.total_tracks,
            "disc_number": self.disc_number,
            "total_discs": self.total_discs,
            "year": self.year,
            "genre": self.genre,
        }

    def as_dict(self) -> dict:
        """Serialize the track to a dictionary (for database storage).

        Returns:
            Dictionary of track attributes (excludes binary cover_art_data).
        """
        return {
            "file_path": str(self.file_path),
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "album_artist": self.album_artist,
            "track_number": self.track_number,
            "total_tracks": self.total_tracks,
            "disc_number": self.disc_number,
            "total_discs": self.total_discs,
            "year": self.year,
            "genre": self.genre,
            "duration": self.duration,
            "fingerprint": self.fingerprint,
            "acoustid": self.acoustid,
            "musicbrainz_recording_id": self.musicbrainz_recording_id,
            "musicbrainz_release_id": self.musicbrainz_release_id,
            "cover_art_url": self.cover_art_url,
            "file_format": self.file_format,
            "file_size_mb": self.file_size_mb,
            "bitrate": self.bitrate,
            "sample_rate": self.sample_rate,
            "is_compilation": self.is_compilation,
            "state": self.state.value,
            "confidence": self.confidence,
            "original_path": str(self.original_path) if self.original_path else None,
            "error_message": self.error_message,
        }
