"""Data access layer -- repository pattern for track and history operations."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.models.track import Track
from src.models.processing_state import ProcessingState
from src.utils.logger import get_logger

logger = get_logger("db.repositories")

# Terminal states that mean "fully processed -- skip on re-run"
_TERMINAL_STATES = frozenset({
    ProcessingState.AUTO_MATCHED.value,
    ProcessingState.COMPLETED.value,
    ProcessingState.NEEDS_REVIEW.value,
    ProcessingState.UNMATCHED.value,
})


class TrackRepository:
    """Data access layer for Track objects in the SQLite database."""

    # Whitelist of allowed column names for SQL construction.
    # Prevents SQL injection if Track.as_dict() ever returns unexpected keys.
    _VALID_COLUMNS: frozenset[str] = frozenset({
        "file_path", "title", "artist", "album", "album_artist",
        "track_number", "total_tracks", "disc_number", "total_discs",
        "year", "genre", "duration", "fingerprint", "acoustid",
        "musicbrainz_recording_id", "musicbrainz_release_id",
        "cover_art_url", "file_format", "file_size_mb", "bitrate",
        "sample_rate", "is_compilation", "state", "confidence",
        "original_path", "error_message",
    })

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Initialize with an active database connection.

        Args:
            connection: SQLite connection (with Row factory enabled).
        """
        self._conn = connection

    def save(self, track: Track) -> int:
        """Insert or update a track in the database.

        Args:
            track: Track to save.

        Returns:
            The database ID of the track.

        Raises:
            ValueError: If as_dict() contains keys not in the column whitelist.
        """
        data = track.as_dict()

        # Validate column names against the whitelist
        invalid = set(data.keys()) - self._VALID_COLUMNS
        if invalid:
            raise ValueError(
                f"Track.as_dict() contains unexpected keys: {invalid}"
            )

        if track.id is not None:
            # Update existing by ID
            set_clause = ", ".join(f"{k} = ?" for k in data.keys())
            values = list(data.values()) + [track.id]
            self._conn.execute(
                f"UPDATE tracks SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                values,
            )
            self._conn.commit()
            return track.id

        # Check if a row with this file_path already exists (resume scenario)
        fp = data.get("file_path")
        if fp:
            cursor = self._conn.execute(
                "SELECT id FROM tracks WHERE file_path = ?", (fp,)
            )
            existing = cursor.fetchone()
            if existing:
                track.id = existing["id"]
                set_clause = ", ".join(f"{k} = ?" for k in data.keys())
                values = list(data.values()) + [track.id]
                self._conn.execute(
                    f"UPDATE tracks SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    values,
                )
                self._conn.commit()
                return track.id

        # Insert new
        columns = ", ".join(data.keys())
        placeholders = ", ".join("?" for _ in data)
        cursor = self._conn.execute(
            f"INSERT INTO tracks ({columns}) VALUES ({placeholders})",
            list(data.values()),
        )
        self._conn.commit()
        track.id = cursor.lastrowid
        return track.id

    def save_batch(self, tracks: list[Track]) -> None:
        """Save multiple tracks in a single transaction.

        Args:
            tracks: List of tracks to save.
        """
        try:
            for track in tracks:
                self.save(track)
        except sqlite3.Error as e:
            self._conn.rollback()
            logger.error("Batch save failed: %s", e)
            raise

    def get_by_id(self, track_id: int) -> Track | None:
        """Retrieve a track by its database ID.

        Args:
            track_id: Database ID.

        Returns:
            Track object, or None if not found.
        """
        cursor = self._conn.execute(
            "SELECT * FROM tracks WHERE id = ?", (track_id,)
        )
        row = cursor.fetchone()
        if row:
            return self._row_to_track(row)
        return None

    def get_by_path(self, file_path: Path | str) -> Track | None:
        """Retrieve a track by its file path.

        Args:
            file_path: File path to look up.

        Returns:
            Track object, or None if not found.
        """
        cursor = self._conn.execute(
            "SELECT * FROM tracks WHERE file_path = ?", (str(file_path),)
        )
        row = cursor.fetchone()
        if row:
            return self._row_to_track(row)
        return None

    def get_by_state(self, state: ProcessingState) -> list[Track]:
        """Retrieve all tracks with a given processing state.

        Args:
            state: Processing state to filter by.

        Returns:
            List of matching tracks.
        """
        cursor = self._conn.execute(
            "SELECT * FROM tracks WHERE state = ? ORDER BY artist, album, track_number",
            (state.value,),
        )
        return [self._row_to_track(row) for row in cursor.fetchall()]

    def get_all(self) -> list[Track]:
        """Retrieve all tracks from the database.

        Returns:
            List of all tracks.
        """
        cursor = self._conn.execute(
            "SELECT * FROM tracks ORDER BY artist, album, track_number"
        )
        return [self._row_to_track(row) for row in cursor.fetchall()]

    def get_stats(self) -> dict[str, int]:
        """Get counts of tracks by processing state.

        Returns:
            Dictionary mapping state name to count.
        """
        cursor = self._conn.execute(
            "SELECT state, COUNT(*) as count FROM tracks GROUP BY state"
        )
        return {row["state"]: row["count"] for row in cursor.fetchall()}

    def delete(self, track_id: int) -> bool:
        """Delete a track from the database.

        Args:
            track_id: Database ID of the track to delete.

        Returns:
            True if a row was deleted.
        """
        cursor = self._conn.execute(
            "DELETE FROM tracks WHERE id = ?", (track_id,)
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def get_processed_paths(self) -> set[str]:
        """Return the set of file paths that have already been processed.

        A track is considered "processed" if its state is a terminal state
        (auto_matched, completed, needs_review, or unmatched).  This lets
        the batch processor skip them on resume.

        Returns:
            Set of file_path strings for already-processed tracks.
        """
        placeholders = ", ".join("?" for _ in _TERMINAL_STATES)
        cursor = self._conn.execute(
            f"SELECT file_path FROM tracks WHERE state IN ({placeholders})",
            tuple(_TERMINAL_STATES),
        )
        return {row["file_path"] for row in cursor.fetchall()}

    def _row_to_track(self, row: sqlite3.Row) -> Track:
        """Convert a database row to a Track object.

        Args:
            row: SQLite Row object.

        Returns:
            Track instance.
        """
        track = Track(
            file_path=Path(row["file_path"]),
            title=row["title"],
            artist=row["artist"],
            album=row["album"],
            album_artist=row["album_artist"],
            track_number=row["track_number"],
            total_tracks=row["total_tracks"],
            disc_number=row["disc_number"],
            total_discs=row["total_discs"],
            year=row["year"],
            genre=row["genre"],
            duration=row["duration"],
            fingerprint=row["fingerprint"],
            acoustid=row["acoustid"],
            musicbrainz_recording_id=row["musicbrainz_recording_id"],
            musicbrainz_release_id=row["musicbrainz_release_id"],
            cover_art_url=row["cover_art_url"],
            file_format=row["file_format"],
            file_size_mb=row["file_size_mb"] or 0.0,
            bitrate=row["bitrate"],
            sample_rate=row["sample_rate"],
            state=ProcessingState(row["state"]),
            confidence=row["confidence"] or 0.0,
            original_path=Path(row["original_path"]) if row["original_path"] else None,
            error_message=row["error_message"],
            id=row["id"],
        )
        return track


class HistoryRepository:
    """Data access layer for change history (supports rollback)."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Initialize with an active database connection.

        Args:
            connection: SQLite connection.
        """
        self._conn = connection

    def record_change(
        self,
        track_id: int,
        action: str,
        field_name: str | None = None,
        old_value: str | None = None,
        new_value: str | None = None,
    ) -> int:
        """Record a change to the history table.

        Args:
            track_id: ID of the track that was changed.
            action: Type of action ('tag_update', 'file_move', 'organize', etc.).
            field_name: Which field was changed (e.g. 'title', 'file_path').
            old_value: Previous value.
            new_value: New value.

        Returns:
            History entry ID.
        """
        cursor = self._conn.execute(
            """INSERT INTO history (track_id, action, field_name, old_value, new_value)
               VALUES (?, ?, ?, ?, ?)""",
            (track_id, action, field_name, old_value, new_value),
        )
        self._conn.commit()
        return cursor.lastrowid

    def get_history_for_track(self, track_id: int) -> list[dict[str, Any]]:
        """Get all history entries for a track.

        Args:
            track_id: ID of the track.

        Returns:
            List of history entry dictionaries.
        """
        cursor = self._conn.execute(
            "SELECT * FROM history WHERE track_id = ? ORDER BY timestamp DESC",
            (track_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_recent_history(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get the most recent history entries across all tracks.

        Args:
            limit: Maximum number of entries.

        Returns:
            List of history entry dictionaries.
        """
        cursor = self._conn.execute(
            "SELECT * FROM history ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]


class MoveHistoryRepository:
    """Data access layer for file move history (supports rollback across restarts)."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Initialize with an active database connection.

        Args:
            connection: SQLite connection.
        """
        self._conn = connection

    def record_move(
        self,
        original_path: str,
        current_path: str,
        backup_path: str | None = None,
    ) -> int:
        """Record a file move for future rollback.

        Args:
            original_path: Where the file was before organization.
            current_path: Where the file is now.
            backup_path: Path to backup copy, if created.

        Returns:
            Move history entry ID.
        """
        cursor = self._conn.execute(
            """INSERT INTO move_history (original_path, current_path, backup_path)
               VALUES (?, ?, ?)""",
            (original_path, current_path, backup_path),
        )
        self._conn.commit()
        return cursor.lastrowid

    def get_all(self) -> list[dict[str, Any]]:
        """Get all move history entries (newest first).

        Returns:
            List of move history entry dictionaries.
        """
        cursor = self._conn.execute(
            "SELECT * FROM move_history ORDER BY timestamp DESC"
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_by_current_path(self, current_path: str) -> dict[str, Any] | None:
        """Find a move history entry by the current (organized) path.

        Args:
            current_path: The file's organized location.

        Returns:
            Move history dict, or None if not found.
        """
        cursor = self._conn.execute(
            "SELECT * FROM move_history WHERE current_path = ?",
            (current_path,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def remove(self, entry_id: int) -> bool:
        """Remove a move history entry after successful rollback.

        Args:
            entry_id: Database ID of the entry.

        Returns:
            True if a row was deleted.
        """
        cursor = self._conn.execute(
            "DELETE FROM move_history WHERE id = ?", (entry_id,)
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def remove_by_current_path(self, current_path: str) -> bool:
        """Remove a move history entry by current path.

        Args:
            current_path: The file's organized location.

        Returns:
            True if a row was deleted.
        """
        cursor = self._conn.execute(
            "DELETE FROM move_history WHERE current_path = ?",
            (current_path,),
        )
        self._conn.commit()
        return cursor.rowcount > 0


class ProcessingRunRepository:
    """Data access layer for batch processing run records."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Initialize with an active database connection.

        Args:
            connection: SQLite connection.
        """
        self._conn = connection

    def start_run(self, source_path: str, total_files: int) -> int:
        """Record the start of a processing run.

        Args:
            source_path: Source directory that was processed.
            total_files: Number of files in the run.

        Returns:
            Run ID.
        """
        cursor = self._conn.execute(
            """INSERT INTO processing_runs (source_path, total_files)
               VALUES (?, ?)""",
            (source_path, total_files),
        )
        self._conn.commit()
        return cursor.lastrowid

    def complete_run(
        self,
        run_id: int,
        auto_matched: int,
        needs_review: int,
        unmatched: int,
        errors: int,
    ) -> None:
        """Record the completion of a processing run.

        Args:
            run_id: Run ID from start_run.
            auto_matched: Number of auto-matched tracks.
            needs_review: Number needing review.
            unmatched: Number unmatched.
            errors: Number of errors.
        """
        self._conn.execute(
            """UPDATE processing_runs
               SET auto_matched = ?, needs_review = ?, unmatched = ?,
                   errors = ?, completed_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (auto_matched, needs_review, unmatched, errors, run_id),
        )
        self._conn.commit()

    def get_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get recent processing runs.

        Args:
            limit: Maximum number of runs.

        Returns:
            List of run dictionaries.
        """
        cursor = self._conn.execute(
            "SELECT * FROM processing_runs ORDER BY started_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]


class ApiCacheRepository:
    """Lightweight key-value cache for API responses.

    Avoids redundant network calls on resume / re-runs.  Each entry is
    keyed by a string (e.g. ``mb_recording:<mbid>``) and stores the raw
    API response as JSON.

    Entries older than ``max_age_days`` are pruned on ``prune()``.
    """

    DEFAULT_MAX_AGE_DAYS = 30

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Initialize with an active database connection.

        Args:
            connection: SQLite connection (with Row factory enabled).
        """
        self._conn = connection

    # --- Public API ---

    def get(self, cache_key: str) -> dict | list | None:
        """Retrieve a cached API response.

        Args:
            cache_key: The cache key (e.g. ``mb_recording:<mbid>``).

        Returns:
            Deserialized JSON (dict or list), or ``None`` on miss.
        """
        cursor = self._conn.execute(
            "SELECT response_json FROM api_cache WHERE cache_key = ?",
            (cache_key,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        try:
            return json.loads(row["response_json"])
        except (json.JSONDecodeError, TypeError):
            return None

    def put(self, cache_key: str, data: dict | list) -> None:
        """Store an API response in the cache.

        Uses ``INSERT OR REPLACE`` so repeated puts for the same key
        update the value and timestamp.

        Args:
            cache_key: The cache key.
            data: JSON-serializable response data.
        """
        self._conn.execute(
            """INSERT OR REPLACE INTO api_cache (cache_key, response_json, created_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)""",
            (cache_key, json.dumps(data, ensure_ascii=False)),
        )
        self._conn.commit()

    def prune(self, max_age_days: int | None = None) -> int:
        """Delete cache entries older than *max_age_days*.

        Args:
            max_age_days: Maximum age in days.  Defaults to 30.

        Returns:
            Number of rows deleted.
        """
        days = max_age_days if max_age_days is not None else self.DEFAULT_MAX_AGE_DAYS
        cursor = self._conn.execute(
            "DELETE FROM api_cache WHERE created_at < datetime('now', ?)",
            (f"-{days} days",),
        )
        self._conn.commit()
        deleted = cursor.rowcount
        if deleted:
            logger.info("Pruned %d expired API cache entries", deleted)
        return deleted
