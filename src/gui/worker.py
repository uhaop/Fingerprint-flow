"""Background worker thread for running the batch processor without freezing the GUI."""

from __future__ import annotations

from pathlib import Path
from PyQt6.QtCore import QThread, pyqtSignal, QObject

from src.models.track import Track
from src.models.match_result import MatchCandidate, MatchResult
from src.models.processing_state import ProcessingState
from src.core.batch_processor import BatchProcessor, BatchResult, BatchStats
from src.core.scanner import FileScanner
from src.core.tag_editor import TagEditor
from src.core.file_organizer import FileOrganizer
from src.utils.logger import get_logger

logger = get_logger("gui.worker")

# Type alias for review selections
ReviewSelection = tuple  # (Track, MatchCandidate)


class ProcessingWorker(QObject):
    """Runs the batch processing pipeline in a background thread.

    Emits Qt signals for progress updates so the GUI can update safely
    from the main thread.

    Signals:
        progress_updated: (current, total, filename, status_message)
        stats_updated: (processed, auto_matched, needs_review, unmatched, errors)
        scan_completed: (total_files_found)
        processing_finished: (BatchResult)
        error_occurred: (error_message)
    """

    progress_updated = pyqtSignal(int, int, str, str)
    stats_updated = pyqtSignal(int, int, int, int, int)
    scan_completed = pyqtSignal(int)
    processing_finished = pyqtSignal(object)  # BatchResult
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        paths: list[str],
        config: dict,
        dry_run: bool = False,
        parent: QObject | None = None,
    ) -> None:
        """Initialize the worker.

        Args:
            paths: List of file or folder paths to process.
            config: Application configuration dictionary.
            dry_run: If True, run identification/scoring only -- skip
                all destructive operations (tag writes, file moves).
        """
        super().__init__(parent)
        self._paths = paths
        self._config = config
        self._dry_run = dry_run
        self._processor: BatchProcessor | None = None

    def run(self) -> None:
        """Execute the batch processing pipeline. Called when the thread starts."""
        try:
            acoustid_key = self._config.get("acoustid_api_key", "")
            discogs_token = self._config.get("discogs_token", "")
            library_path = self._config.get("library_path", "")
            backup_path = self._config.get("backup_path", "")
            keep_originals = self._config.get("keep_originals", True)
            auto_threshold = self._config.get("auto_apply_threshold", 90)
            review_threshold = self._config.get("review_threshold", 70)
            fpcalc_available = self._config.get("_fpcalc_available", True)
            move_unmatched = self._config.get("move_unmatched", False)
            archive_org_enabled = self._config.get("archive_org_enabled", True)

            # Only require AcoustID key when fingerprinting is available
            if not acoustid_key and fpcalc_available:
                self.error_occurred.emit(
                    "AcoustID API key not configured. Go to Settings and enter your key."
                )
                return

            if not library_path:
                self.error_occurred.emit(
                    "Library path not configured. Go to Settings and set your output folder."
                )
                return

            # Create the batch processor with our progress callback
            move_repo = self._config.get("_move_repo")
            track_repo = self._config.get("_track_repo")
            api_cache = self._config.get("_api_cache")
            max_fp = self._config.get("max_concurrent_fingerprints")
            self._processor = BatchProcessor(
                acoustid_api_key=acoustid_key,
                discogs_token=discogs_token or None,
                library_path=Path(library_path),
                backup_path=Path(backup_path) if backup_path else None,
                keep_originals=keep_originals,
                auto_threshold=auto_threshold,
                review_threshold=review_threshold,
                progress_callback=self._on_progress,
                fpcalc_available=fpcalc_available,
                move_unmatched=move_unmatched,
                archive_org_enabled=archive_org_enabled,
                move_repo=move_repo,
                dry_run=self._dry_run,
                max_concurrent_fingerprints=max_fp,
                track_repo=track_repo,
                api_cache=api_cache,
            )

            # Log what we received for debugging
            for p in self._paths:
                logger.info("Input path: %s (is_dir=%s, exists=%s)",
                            p, Path(p).is_dir(), Path(p).exists())

            # Scan once and reuse the track list -- avoids a double filesystem scan.
            scanner = FileScanner()
            pre_scan_tracks = scanner.scan_files(self._paths)
            file_count = len(pre_scan_tracks)
            self.scan_completed.emit(file_count)

            if file_count == 0:
                self.error_occurred.emit(
                    "No audio files found in the selected items.\n\n"
                    "Make sure you selected files with supported extensions:\n"
                    "MP3, FLAC, M4A, OGG, WAV, AIFF, WMA, APE, WV, OPUS"
                )
                return

            result = self._processor.process_prescanned(pre_scan_tracks)

            # Emit final stats
            self._emit_stats(result.stats)
            self.processing_finished.emit(result)

            logger.info("Worker finished: %d tracks processed", result.stats.total)

        except Exception as e:
            logger.error("Worker error: %s", e, exc_info=True)
            self.error_occurred.emit(str(e))

    def pause(self) -> None:
        """Pause the batch processor."""
        if self._processor:
            self._processor.pause()

    def resume(self) -> None:
        """Resume the batch processor."""
        if self._processor:
            self._processor.resume()

    def cancel(self) -> None:
        """Cancel the batch processor."""
        if self._processor:
            self._processor.cancel()

    def _on_progress(
        self, current: int, total: int, track: Track, message: str
    ) -> None:
        """Progress callback from the batch processor -- emit Qt signals."""
        self.progress_updated.emit(current, total, track.file_path.name, message)

        # Emit live running stats from the batch result kept on the processor
        if self._processor and self._processor.current_result:
            stats = self._processor.current_result.stats
            self.stats_updated.emit(
                stats.processed,
                stats.auto_matched,
                stats.needs_review,
                stats.unmatched,
                stats.errors,
            )
        else:
            self.stats_updated.emit(current, 0, 0, 0, 0)

    def _emit_stats(self, stats: BatchStats) -> None:
        """Emit final stats."""
        self.stats_updated.emit(
            stats.processed,
            stats.auto_matched,
            stats.needs_review,
            stats.unmatched,
            stats.errors,
        )


class ReviewApplyWorker(QObject):
    """Applies user-selected review matches in a background thread.

    Processes all (Track, MatchCandidate) pairs: writes tags, downloads
    cover art, and organizes each file into the library.

    Signals:
        progress_updated: (current, total, filename, status_message)
        finished: (applied_count, duplicate_count, error_count)
        error_occurred: (error_message)
    """

    progress_updated = pyqtSignal(int, int, str, str)
    finished = pyqtSignal(int, int, int)  # applied, duplicates, errors
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        selections: list[ReviewSelection],
        config: dict,
        parent: QObject | None = None,
    ) -> None:
        """Initialize the review apply worker.

        Args:
            selections: List of (Track, MatchCandidate) tuples to apply.
            config: Application configuration dictionary.
        """
        super().__init__(parent)
        self._selections = selections
        self._config = config

    def run(self) -> None:
        """Apply all selected matches. Called when the thread starts."""
        applied = 0
        duplicates = 0
        errors = 0
        total = len(self._selections)

        try:
            processor = BatchProcessor(
                acoustid_api_key=self._config.get("acoustid_api_key", ""),
                discogs_token=self._config.get("discogs_token") or None,
                library_path=Path(self._config.get("library_path", "")),
                backup_path=(
                    Path(self._config.get("backup_path", ""))
                    if self._config.get("backup_path")
                    else None
                ),
                keep_originals=self._config.get("keep_originals", True),
            )

            for idx, (track, candidate) in enumerate(self._selections, start=1):
                filename = track.file_path.name
                self.progress_updated.emit(
                    idx, total, filename,
                    f"Applying: {candidate.artist} - {candidate.title}",
                )

                try:
                    processor.apply_match(track, candidate)

                    if track.error_message and "Duplicate" in track.error_message:
                        duplicates += 1
                        logger.info("Duplicate skipped: %s", filename)
                    else:
                        applied += 1
                        logger.info("Applied: %s -> %s - %s", filename, candidate.artist, candidate.title)

                except Exception as e:
                    errors += 1
                    logger.error("Failed to apply match for %s: %s", filename, e)

            logger.info(
                "Review apply complete: %d applied, %d duplicates, %d errors",
                applied, duplicates, errors,
            )

        except Exception as e:
            logger.error("Review apply worker error: %s", e, exc_info=True)
            self.error_occurred.emit(str(e))
            return

        self.finished.emit(applied, duplicates, errors)


class PreviewApplyWorker(QObject):
    """Applies approved tracks from the Preview Report in a background thread.

    Takes tracks that were identified during a dry-run and applies the
    destructive operations (backup, tag write, file organize) using
    the match data already cached on each Track.

    Signals:
        progress_updated: (current, total, filename, status_message)
        finished: (applied_count, duplicate_count, error_count)
        error_occurred: (error_message)
    """

    progress_updated = pyqtSignal(int, int, str, str)
    finished = pyqtSignal(int, int, int)  # applied, duplicates, errors
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        tracks: list[Track],
        match_results: dict[str, MatchResult],
        config: dict,
        parent: QObject | None = None,
    ) -> None:
        """Initialize the preview apply worker.

        Args:
            tracks: List of approved auto-matched Track objects.
            match_results: Dict mapping original file paths to MatchResults.
            config: Application configuration dictionary.
        """
        super().__init__(parent)
        self._tracks = tracks
        self._match_results = match_results
        self._config = config

    def run(self) -> None:
        """Apply all approved tracks. Called when the thread starts."""
        applied = 0
        duplicates = 0
        errors = 0
        total = len(self._tracks)

        try:
            library_path = Path(self._config.get("library_path", ""))
            backup_path = (
                Path(self._config.get("backup_path", ""))
                if self._config.get("backup_path")
                else None
            )
            keep_originals = self._config.get("keep_originals", True)
            move_repo = self._config.get("_move_repo")

            tag_editor = TagEditor()
            organizer = FileOrganizer(
                library_path,
                backup_path,
                keep_originals,
                move_repo=move_repo,
            )

            for idx, track in enumerate(self._tracks, start=1):
                filename = track.file_path.name
                self.progress_updated.emit(
                    idx, total, filename,
                    f"Applying: {track.display_artist} - {track.display_title}",
                )

                try:
                    # The track still has its original file_path (dry-run
                    # updated it to the *proposed* path).  Restore it so
                    # organizer can find the real file on disk.
                    if track.original_path and track.original_path.exists():
                        track.file_path = track.original_path

                    # 1. Backup
                    organizer.backup_before_changes(track)

                    # 2. Write tags
                    if tag_editor.write_tags(track):
                        logger.info(
                            "Applied tags: %s - %s",
                            track.display_artist, track.display_title,
                        )
                    else:
                        logger.warning(
                            "Failed to write tags for: %s", track.file_path,
                        )

                    # 3. Download cover art if available
                    match_key = str(track.original_path or track.file_path)
                    match_result = self._match_results.get(match_key)
                    if match_result and match_result.best_match:
                        candidate = match_result.best_match
                        if candidate.cover_art_url and candidate.musicbrainz_release_id:
                            try:
                                from src.core.metadata_fetcher import MetadataFetcher
                                fetcher = MetadataFetcher(
                                    discogs_token=self._config.get("discogs_token") or None,
                                )
                                art_data = fetcher.fetch_cover_art(
                                    candidate.musicbrainz_release_id,
                                )
                                if art_data:
                                    tag_editor.write_cover_art(track, art_data)
                                    track.cover_art_data = art_data
                            except Exception as art_err:
                                logger.warning(
                                    "Cover art download failed for %s: %s",
                                    filename, art_err,
                                )

                    # 4. Organize (move to library structure)
                    track = organizer.organize(track)

                    if track.error_message and "Duplicate" in track.error_message:
                        duplicates += 1
                        logger.info("Duplicate skipped: %s", filename)
                    else:
                        track.state = ProcessingState.COMPLETED
                        applied += 1
                        logger.info(
                            "Preview apply: %s -> %s",
                            filename, track.file_path,
                        )

                except Exception as e:
                    errors += 1
                    track.state = ProcessingState.ERROR
                    track.error_message = str(e)
                    logger.error(
                        "Failed to apply %s: %s", filename, e,
                    )

            logger.info(
                "Preview apply complete: %d applied, %d duplicates, %d errors",
                applied, duplicates, errors,
            )

        except Exception as e:
            logger.error("Preview apply worker error: %s", e, exc_info=True)
            self.error_occurred.emit(str(e))
            return

        self.finished.emit(applied, duplicates, errors)


class ManualSearchWorker(QObject):
    """Runs a manual metadata search in a background thread.

    Used when the user types a custom query in the review view's
    inline search panel.

    Signals:
        results_ready: (track_id, List[MatchCandidate])
        error_occurred: (error_message)
    """

    results_ready = pyqtSignal(int, list)  # track_id, candidates
    error_occurred = pyqtSignal(str)

    # Source constants
    SOURCE_ALL = "all"
    SOURCE_MUSICBRAINZ = "musicbrainz"
    SOURCE_DISCOGS = "discogs"

    def __init__(
        self,
        track_id: int,
        title: str,
        artist: str,
        config: dict,
        album: str = "",
        source: str = "all",
        parent: QObject | None = None,
    ) -> None:
        """Initialize the manual search worker.

        Args:
            track_id: id(track) to route results back to the correct card.
            title: Title search term.
            artist: Artist search term.
            config: Application configuration dictionary.
            album: Album search term.
            source: Which API to search -- "all", "musicbrainz", or "discogs".
        """
        super().__init__(parent)
        self._track_id = track_id
        self._title = title
        self._artist = artist
        self._album = album
        self._source = source
        self._config = config

    def run(self) -> None:
        """Search the selected source(s) for the given query."""
        try:
            from src.core.metadata_fetcher import MetadataFetcher

            fetcher = MetadataFetcher(
                discogs_token=self._config.get("discogs_token") or None,
            )

            candidates: list = []

            # Search MusicBrainz (unless user picked Discogs-only)
            if self._source in (self.SOURCE_ALL, self.SOURCE_MUSICBRAINZ):
                mb = fetcher.search_musicbrainz(
                    title=self._title or None,
                    artist=self._artist or None,
                    album=self._album or None,
                )
                candidates.extend(mb)

            # Search Discogs (unless user picked MusicBrainz-only)
            if self._source in (self.SOURCE_ALL, self.SOURCE_DISCOGS):
                discogs = fetcher.search_discogs(
                    title=self._title or None,
                    artist=self._artist or None,
                    album=self._album or None,
                )
                candidates.extend(discogs)

            logger.info(
                "Manual search for '%s' / '%s' / album='%s' [%s]: %d results",
                self._title, self._artist, self._album, self._source,
                len(candidates),
            )
            self.results_ready.emit(self._track_id, candidates)

        except Exception as e:
            logger.error("Manual search error: %s", e, exc_info=True)
            self.error_occurred.emit(str(e))
