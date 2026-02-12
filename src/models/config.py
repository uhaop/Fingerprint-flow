"""Typed configuration model for Fingerprint Flow.

Replaces the raw ``dict`` that was passed throughout the application.  All
configuration values now have explicit types, defaults, and documentation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from src.utils.constants import (
    DEFAULT_AUTO_APPLY_THRESHOLD,
    DEFAULT_REVIEW_THRESHOLD,
    DEFAULT_FOLDER_TEMPLATE,
    DEFAULT_FILE_TEMPLATE,
    DEFAULT_SINGLES_FOLDER,
    DEFAULT_UNMATCHED_FOLDER,
    DEFAULT_THEME,
    DEFAULT_WINDOW_WIDTH,
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_BATCH_SIZE,
    DEFAULT_MAX_CONCURRENT_FINGERPRINTS,
    MUSICBRAINZ_RATE_LIMIT,
    DISCOGS_RATE_LIMIT,
    ARCHIVE_ORG_RATE_LIMIT,
)


@dataclass
class AppConfig:
    """Strongly-typed configuration for the Fingerprint Flow application.

    Attributes:
        library_path: Root directory for the organized music library.
        backup_path: Directory for backing up originals. If empty, uses
            ``library_path/_Backups``.
        keep_originals: Whether to back up original files before modifying them.
        folder_template: Template for folder structure (supports
            ``{artist}``, ``{album}``, ``{year}``, ``{disc}``).
        file_template: Template for file naming (supports
            ``{track}``, ``{title}``, ``{disc}``).
        singles_folder: Folder name for tracks without an album.
        unmatched_folder: Folder name for unmatched files.
        move_unmatched: If True, move unmatched files to the unmatched folder
            instead of leaving them in place.
        auto_apply_threshold: Confidence threshold (0-100) for auto-apply.
        review_threshold: Confidence threshold (0-100) for review queue.
        acoustid_api_key: AcoustID API key for fingerprint lookups.
        discogs_token: Discogs personal access token.
        musicbrainz_rate_limit: Seconds between MusicBrainz requests.
        discogs_rate_limit: Seconds between Discogs requests.
        archive_org_rate_limit: Seconds between Internet Archive requests.
        archive_org_enabled: Whether to use Internet Archive as a metadata source.
        max_concurrent_fingerprints: Number of parallel fingerprint operations.
        batch_size: Files per processing batch.
        theme: GUI theme ("dark" or "light").
        window_width: Initial GUI window width.
        window_height: Initial GUI window height.
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR).
        log_file: Path to log file (None = console only).
        dry_run: If True, simulate all operations without modifying files.
    """

    # --- Output ---
    library_path: str = ""
    backup_path: str = ""
    keep_originals: bool = True

    # --- File Organization ---
    folder_template: str = DEFAULT_FOLDER_TEMPLATE
    file_template: str = DEFAULT_FILE_TEMPLATE
    singles_folder: str = DEFAULT_SINGLES_FOLDER
    unmatched_folder: str = DEFAULT_UNMATCHED_FOLDER
    move_unmatched: bool = False

    # --- Confidence ---
    auto_apply_threshold: float = DEFAULT_AUTO_APPLY_THRESHOLD
    review_threshold: float = DEFAULT_REVIEW_THRESHOLD

    # --- API Keys ---
    acoustid_api_key: str = ""
    discogs_token: str = ""

    # --- Rate Limits ---
    musicbrainz_rate_limit: float = MUSICBRAINZ_RATE_LIMIT
    discogs_rate_limit: float = DISCOGS_RATE_LIMIT
    archive_org_rate_limit: float = ARCHIVE_ORG_RATE_LIMIT

    # --- Internet Archive ---
    archive_org_enabled: bool = True

    # --- Processing ---
    max_concurrent_fingerprints: int = DEFAULT_MAX_CONCURRENT_FINGERPRINTS
    batch_size: int = DEFAULT_BATCH_SIZE

    # --- GUI ---
    theme: str = DEFAULT_THEME
    window_width: int = DEFAULT_WINDOW_WIDTH
    window_height: int = DEFAULT_WINDOW_HEIGHT

    # --- Logging ---
    log_level: str = "INFO"
    log_file: str | None = None

    # --- Safety ---
    dry_run: bool = False

    # --- Runtime State (set by main, not from config file) ---
    fpcalc_available: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> AppConfig:
        """Create an AppConfig from a raw dictionary (e.g., from YAML).

        Unknown keys are silently ignored so YAML files with extra comments
        or future keys don't break older code.

        Args:
            data: Dictionary of configuration values.

        Returns:
            Populated AppConfig instance.
        """
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields and v is not None}
        return cls(**filtered)

    def to_dict(self) -> dict:
        """Serialize the config to a dictionary.

        Returns:
            Dictionary of all configuration values.
        """
        from dataclasses import asdict
        return asdict(self)

    @property
    def library_path_resolved(self) -> Path | None:
        """Return the library_path as a resolved Path, or None if not set."""
        if not self.library_path:
            return None
        return Path(self.library_path).expanduser().resolve()

    @property
    def backup_path_resolved(self) -> Path | None:
        """Return the backup_path as a resolved Path, or None if not set."""
        if not self.backup_path:
            return None
        return Path(self.backup_path).expanduser().resolve()
