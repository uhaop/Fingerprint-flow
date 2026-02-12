"""SQLite database for processing state, history, and rollback tracking."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.utils.constants import DEFAULT_DB_FILENAME
from src.utils.logger import get_logger

logger = get_logger("db.database")

SCHEMA_VERSION = 3

CREATE_TABLES_SQL = """
-- Tracks: stores all known audio files and their metadata
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL UNIQUE,
    original_path TEXT,
    title TEXT,
    artist TEXT,
    album TEXT,
    album_artist TEXT,
    track_number INTEGER,
    total_tracks INTEGER,
    disc_number INTEGER,
    total_discs INTEGER,
    year INTEGER,
    genre TEXT,
    duration REAL,
    fingerprint TEXT,
    acoustid TEXT,
    musicbrainz_recording_id TEXT,
    musicbrainz_release_id TEXT,
    cover_art_url TEXT,
    file_format TEXT,
    file_size_mb REAL,
    bitrate INTEGER,
    sample_rate INTEGER,
    state TEXT NOT NULL DEFAULT 'pending',
    confidence REAL DEFAULT 0.0,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- History: tracks every change for rollback capability
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    field_name TEXT,
    old_value TEXT,
    new_value TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (track_id) REFERENCES tracks(id)
);

-- Processing runs: logs each batch processing run
CREATE TABLE IF NOT EXISTS processing_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path TEXT NOT NULL,
    total_files INTEGER DEFAULT 0,
    auto_matched INTEGER DEFAULT 0,
    needs_review INTEGER DEFAULT 0,
    unmatched INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

-- Move history: persists file moves for rollback across app restarts
CREATE TABLE IF NOT EXISTS move_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    original_path TEXT NOT NULL,
    current_path TEXT NOT NULL,
    backup_path TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- API response cache: avoids re-querying APIs on resume / re-runs
CREATE TABLE IF NOT EXISTS api_cache (
    cache_key TEXT PRIMARY KEY,
    response_json TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_tracks_state ON tracks(state);
CREATE INDEX IF NOT EXISTS idx_tracks_artist ON tracks(artist);
CREATE INDEX IF NOT EXISTS idx_tracks_album ON tracks(album);
CREATE INDEX IF NOT EXISTS idx_history_track ON history(track_id);
CREATE INDEX IF NOT EXISTS idx_move_history_current ON move_history(current_path);
CREATE INDEX IF NOT EXISTS idx_api_cache_created ON api_cache(created_at);
"""


class Database:
    """SQLite database manager for Fingerprint Flow.

    Handles connection management, schema creation, and migrations.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        """Initialize the database.

        Args:
            db_path: Path to the SQLite database file. If None, uses
                the default filename in the current directory.
        """
        self._db_path = Path(db_path) if db_path else Path(DEFAULT_DB_FILENAME)
        self._connection: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        """Open a connection to the database and ensure schema is created.

        Returns:
            Active SQLite connection.
        """
        if self._connection is not None:
            return self._connection

        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        # check_same_thread=False is safe here because:
        # 1. WAL mode allows concurrent readers + one writer
        # 2. Write operations (save, cache put) are serialized per-track
        # 3. The GUI worker (QThread) needs to share the connection
        self._connection = sqlite3.connect(
            str(self._db_path),
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")

        self._ensure_schema()
        logger.info("Database connected: %s", self._db_path)
        return self._connection

    def close(self) -> None:
        """Close the database connection."""
        if self._connection:
            self._connection.close()
            self._connection = None
            logger.debug("Database connection closed")

    @property
    def connection(self) -> sqlite3.Connection:
        """Get the active connection, connecting if necessary."""
        if self._connection is None:
            return self.connect()
        return self._connection

    def _ensure_schema(self) -> None:
        """Create tables if they don't exist and run migrations if needed."""
        conn = self._connection
        if conn is None:
            return

        conn.executescript(CREATE_TABLES_SQL)

        # Check/set schema version
        cursor = conn.execute("SELECT COUNT(*) FROM schema_version")
        count = cursor.fetchone()[0]

        if count == 0:
            conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (SCHEMA_VERSION,),
            )
            conn.commit()
            logger.info("Database schema created (version %d)", SCHEMA_VERSION)
        else:
            cursor = conn.execute("SELECT version FROM schema_version")
            current_version = cursor.fetchone()[0]
            if current_version < SCHEMA_VERSION:
                self._migrate(current_version, SCHEMA_VERSION)

    def _migrate(self, from_version: int, to_version: int) -> None:
        """Run database migrations between versions.

        Args:
            from_version: Current schema version.
            to_version: Target schema version.
        """
        logger.info("Migrating database from v%d to v%d", from_version, to_version)
        conn = self._connection
        if not conn:
            return

        if from_version < 2:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS move_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    original_path TEXT NOT NULL,
                    current_path TEXT NOT NULL,
                    backup_path TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_move_history_current
                    ON move_history(current_path);
            """)
            logger.info("Migration v1->v2: created move_history table")

        if from_version < 3:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS api_cache (
                    cache_key TEXT PRIMARY KEY,
                    response_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_api_cache_created
                    ON api_cache(created_at);
            """)
            logger.info("Migration v2->v3: created api_cache table")

        conn.execute("UPDATE schema_version SET version = ?", (to_version,))
        conn.commit()

    def __enter__(self) -> Database:
        """Open the database connection for use as a context manager."""
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type | None,
        exc_val: BaseException | None,
        exc_tb: object | None,
    ) -> None:
        """Close the database connection when exiting the context."""
        self.close()
